"""画面の変化検知 (F-05〜F-10)。

画像を縮小・グレースケール化した「シグネチャ」同士を比べ、明るさの差が
``pixel_threshold`` を超えた画素の割合を「変化の大きさ」とする。

検知の流れ:
1. 前回保存した画像(基準)との変化が ``change_threshold`` 以上になったら「落ち着き待ち」に入る
2. 連続フレーム間の変化が ``stable_threshold`` 未満の状態が ``settle_sec`` 秒続いたら撮影する
   (``settle_max_sec`` 秒経っても落ち着かない場合も撮影する)
3. 撮影直前に、基準と実質同じ内容に戻っていた場合 (F-09) や、
   保存済みのどれかと同じ内容の場合 (F-10) は保存しない
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from PIL import Image, ImageFilter


def to_signature(img: Image.Image, width: int) -> np.ndarray:
    """比較用のシグネチャ(縮小・ぼかし済みのグレースケール配列)を作る。"""
    gray = img.convert("L")
    if width > 0 and gray.width > width:
        height = max(1, round(gray.height * width / gray.width))
        gray = gray.resize((width, height), Image.Resampling.BILINEAR)
    # 動画圧縮のノイズや細かなちらつきを無視するため軽くぼかす
    gray = gray.filter(ImageFilter.GaussianBlur(1))
    return np.asarray(gray, dtype=np.int16)


def change_ratio(a: np.ndarray, b: np.ndarray, pixel_threshold: int) -> float:
    """2つのシグネチャ間で変化した画素の割合 (0.0〜1.0) を返す。"""
    if a.shape != b.shape:
        return 1.0
    return float(np.mean(np.abs(a - b) > pixel_threshold))


@dataclass(frozen=True)
class DetectorParams:
    change_threshold: float = 0.03
    pixel_threshold: int = 24
    stable_threshold: float = 0.005
    settle_sec: float = 2.0
    settle_max_sec: float = 10.0
    skip_duplicates: bool = True


class Action(Enum):
    NONE = "none"
    SAVE = "save"


@dataclass(frozen=True)
class Decision:
    action: Action
    change: float = 0.0
    """基準(前回保存画像)からの変化の大きさ"""
    motion: float = 0.0
    """直前のフレームからの変化の大きさ"""
    reason: str = ""


@dataclass
class ChangeDetector:
    reference: np.ndarray | None = None
    history: list[np.ndarray] = field(default_factory=list)
    _prev: np.ndarray | None = None
    _settle_start: float | None = None
    _stable_since: float = 0.0

    @property
    def settling(self) -> bool:
        return self._settle_start is not None

    def reset(self) -> None:
        """新しいセッション用に状態をすべて消す。"""
        self.reference = None
        self.history.clear()
        self.interrupt()

    def interrupt(self) -> None:
        """一時停止時など、落ち着き待ちを取り消す。基準画像は残す (F-36)。"""
        self._prev = None
        self._settle_start = None

    def commit(self, sig: np.ndarray) -> None:
        """保存した画像を新しい基準として記録する。"""
        self.reference = sig
        self.history.append(sig)
        self._settle_start = None

    def feed(self, sig: np.ndarray, now: float, p: DetectorParams) -> Decision:
        motion = change_ratio(sig, self._prev, p.pixel_threshold) if self._prev is not None else 0.0
        self._prev = sig

        if self.reference is None:
            return Decision(Action.SAVE, 1.0, motion, "first")

        change = change_ratio(sig, self.reference, p.pixel_threshold)

        if self._settle_start is None:
            if change < p.change_threshold:
                return Decision(Action.NONE, change, motion)
            self._settle_start = now
            self._stable_since = now
            if p.settle_sec > 0:
                return Decision(Action.NONE, change, motion, "settling")
        elif motion > p.stable_threshold:
            self._stable_since = now

        settled = now - self._stable_since >= p.settle_sec
        timed_out = p.settle_max_sec > 0 and now - self._settle_start >= p.settle_max_sec
        if not (settled or timed_out):
            return Decision(Action.NONE, change, motion, "settling")

        self._settle_start = None
        if change < p.change_threshold:
            # 切り替わったように見えたが元に戻った (F-09)
            return Decision(Action.NONE, change, motion, "reverted")
        if p.skip_duplicates and any(
            change_ratio(sig, h, p.pixel_threshold) < p.change_threshold for h in self.history
        ):
            # 保存済みのスライドに戻った (F-10)。表示中の内容を基準にして再検知を防ぐ
            self.reference = sig
            return Decision(Action.NONE, change, motion, "duplicate")
        return Decision(Action.SAVE, change, motion, "timeout" if not settled else "change")
