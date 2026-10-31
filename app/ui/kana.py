"""五十音图：可随时打开的检索/复制小窗。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# (平假名, 片假名, 罗马字)；None 表示五十音表里的空位。
SEION: list[list[tuple[str, str, str] | None]] = [
    [("あ", "ア", "a"), ("い", "イ", "i"), ("う", "ウ", "u"), ("え", "エ", "e"), ("お", "オ", "o")],
    [("か", "カ", "ka"), ("き", "キ", "ki"), ("く", "ク", "ku"), ("け", "ケ", "ke"), ("こ", "コ", "ko")],
    [("さ", "サ", "sa"), ("し", "シ", "shi"), ("す", "ス", "su"), ("せ", "セ", "se"), ("そ", "ソ", "so")],
    [("た", "タ", "ta"), ("ち", "チ", "chi"), ("つ", "ツ", "tsu"), ("て", "テ", "te"), ("と", "ト", "to")],
    [("な", "ナ", "na"), ("に", "ニ", "ni"), ("ぬ", "ヌ", "nu"), ("ね", "ネ", "ne"), ("の", "ノ", "no")],
    [("は", "ハ", "ha"), ("ひ", "ヒ", "hi"), ("ふ", "フ", "fu"), ("へ", "ヘ", "he"), ("ほ", "ホ", "ho")],
    [("ま", "マ", "ma"), ("み", "ミ", "mi"), ("む", "ム", "mu"), ("め", "メ", "me"), ("も", "モ", "mo")],
    [("や", "ヤ", "ya"), None, ("ゆ", "ユ", "yu"), None, ("よ", "ヨ", "yo")],
    [("ら", "ラ", "ra"), ("り", "リ", "ri"), ("る", "ル", "ru"), ("れ", "レ", "re"), ("ろ", "ロ", "ro")],
    [("わ", "ワ", "wa"), None, None, None, ("を", "ヲ", "wo")],
    [("ん", "ン", "n"), None, None, None, None],
]

DAKUON: list[list[tuple[str, str, str]]] = [
    [("が", "ガ", "ga"), ("ぎ", "ギ", "gi"), ("ぐ", "グ", "gu"), ("げ", "ゲ", "ge"), ("ご", "ゴ", "go")],
    [("ざ", "ザ", "za"), ("じ", "ジ", "ji"), ("ず", "ズ", "zu"), ("ぜ", "ゼ", "ze"), ("ぞ", "ゾ", "zo")],
    [("だ", "ダ", "da"), ("ぢ", "ヂ", "ji"), ("づ", "ヅ", "zu"), ("で", "デ", "de"), ("ど", "ド", "do")],
    [("ば", "バ", "ba"), ("び", "ビ", "bi"), ("ぶ", "ブ", "bu"), ("べ", "ベ", "be"), ("ぼ", "ボ", "bo")],
    [("ぱ", "パ", "pa"), ("ぴ", "ピ", "pi"), ("ぷ", "プ", "pu"), ("ぺ", "ペ", "pe"), ("ぽ", "ポ", "po")],
]

YOON: list[list[tuple[str, str, str]]] = [
    [("きゃ", "キャ", "kya"), ("きゅ", "キュ", "kyu"), ("きょ", "キョ", "kyo")],
    [("しゃ", "シャ", "sha"), ("しゅ", "シュ", "shu"), ("しょ", "ショ", "sho")],
    [("ちゃ", "チャ", "cha"), ("ちゅ", "チュ", "chu"), ("ちょ", "チョ", "cho")],
    [("にゃ", "ニャ", "nya"), ("にゅ", "ニュ", "nyu"), ("にょ", "ニョ", "nyo")],
    [("ひゃ", "ヒャ", "hya"), ("ひゅ", "ヒュ", "hyu"), ("ひょ", "ヒョ", "hyo")],
    [("みゃ", "ミャ", "mya"), ("みゅ", "ミュ", "myu"), ("みょ", "ミョ", "myo")],
    [("りゃ", "リャ", "rya"), ("りゅ", "リュ", "ryu"), ("りょ", "リョ", "ryo")],
    [("ぎゃ", "ギャ", "gya"), ("ぎゅ", "ギュ", "gyu"), ("ぎょ", "ギョ", "gyo")],
    [("じゃ", "ジャ", "ja"), ("じゅ", "ジュ", "ju"), ("じょ", "ジョ", "jo")],
    [("びゃ", "ビャ", "bya"), ("びゅ", "ビュ", "byu"), ("びょ", "ビョ", "byo")],
    [("ぴゃ", "ピャ", "pya"), ("ぴゅ", "ピュ", "pyu"), ("ぴょ", "ピョ", "pyo")],
]

# 小写字母、长音、促音入口单独一行，方便复制。
EXTRAS = [
    ("ぁ", "ァ", "a"), ("ぃ", "ィ", "i"), ("ぅ", "ゥ", "u"), ("ぇ", "ェ", "e"), ("ぉ", "ォ", "o"),
    ("ゃ", "ャ", "ya"), ("ゅ", "ュ", "yu"), ("ょ", "ョ", "yo"), ("っ", "ッ", "tsu"),
    ("ー", "ー", "ー"), ("ゔ", "ヴ", "vu"),
]

KANA_QSS = """
QWidget#KanaRoot {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #141026, stop:0.55 #1b1430, stop:1 #24122b);
    color: #f6e9ff;
}
QFrame#KanaHeader { background: transparent; border: none; }
QLabel#KanaTitle { font-size: 26px; font-weight: 700; color: #ffe6f3; }
QLabel#KanaSub { color: rgba(221, 203, 255, 0.68); font-size: 11px; }
QLineEdit#KanaSearch {
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,143,193,0.28);
    border-radius: 11px; padding: 8px 13px; color: #fff4fb;
    selection-background-color: #ff6fa9;
}
QLineEdit#KanaSearch:focus { border: 1px solid #ff8fc1; }
QCheckBox { color: rgba(255,238,250,0.82); spacing: 7px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid #5e4a78; background: #211a32;
}
QCheckBox::indicator:checked { background: #ff6fa9; border-color: #ff9cc7; }
QTabWidget::pane { border: 1px solid rgba(255,143,193,0.20); border-radius: 12px; background: rgba(13,10,23,0.55); }
QTabBar::tab {
    background: transparent; color: #c7b8df; padding: 9px 18px;
    border: none; border-radius: 9px; margin-right: 4px; font-size: 12px;
}
QTabBar::tab:hover { background: rgba(255,143,193,0.10); color: #ffe6f3; }
QTabBar::tab:selected { background: #5b2c55; color: #fff; }
QFrame#KanaCell {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,0.085), stop:1 rgba(255,143,193,0.045));
    border: 1px solid rgba(255,173,212,0.16); border-radius: 13px;
}
QFrame#KanaCell:hover {
    background: rgba(255,111,169,0.17); border: 1px solid rgba(255,143,193,0.62);
}
QLabel#KanaHira { color: #fff8fc; font-size: 27px; font-weight: 600; }
QLabel#KanaKata { color: #ffb5d5; font-size: 13px; }
QLabel#KanaRomaji { color: rgba(195,190,230,0.75); font-size: 10px; letter-spacing: 1px; }
QLabel#KanaStatus { color: #ffc1dc; font-size: 11px; }
QPushButton#KanaClose {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px; padding: 7px 14px; color: #e8dcff;
}
QPushButton#KanaClose:hover { background: rgba(255,111,169,0.20); border-color: #ff8fc1; }
"""


class KanaCell(QFrame):
    copied = Signal(str, str)

    def __init__(self, hira: str, kata: str, romaji: str, parent=None, compact: bool = False) -> None:
        super().__init__(parent)
        self.hira, self.kata, self.romaji = hira, kata, romaji
        self.setObjectName("KanaCell")
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(43 if compact else 84)
        self.setToolTip(f"左键复制「{hira}」 · 右键复制「{kata}」")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(0)
        hira_label = QLabel(hira, self)
        hira_label.setObjectName("KanaHira")
        hira_label.setAlignment(Qt.AlignCenter)
        hira_label.setFont(self._font("Yu Gothic UI", 22 if compact else 27, QFont.DemiBold))
        kata_label = QLabel(kata, self)
        kata_label.setObjectName("KanaKata")
        kata_label.setAlignment(Qt.AlignCenter)
        kata_label.setFont(self._font("Yu Gothic UI", 11 if compact else 12))
        romaji_label = QLabel(romaji, self)
        romaji_label.setObjectName("KanaRomaji")
        romaji_label.setAlignment(Qt.AlignCenter)
        romaji_label.setFont(self._font("Consolas", 9 if compact else 10))
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(3)
        head.addStretch(1)
        head.addWidget(hira_label)
        head.addWidget(kata_label)
        head.addStretch(1)
        layout.addLayout(head)
        layout.addWidget(romaji_label)
        if compact:
            hira_label.setStyleSheet("font-size: 22px;")
            kata_label.setStyleSheet("font-size: 11px;")
            romaji_label.setStyleSheet("font-size: 9px;")

    @staticmethod
    def _font(family: str, size: int, weight: QFont.Weight = QFont.Normal) -> QFont:
        font = QFont()
        font.setFamilies([family, "Microsoft YaHei UI"])
        font.setPixelSize(size)
        font.setWeight(weight)
        return font

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.copied.emit(self.hira, "平假名")
        elif event.button() == Qt.RightButton:
            self.copied.emit(self.kata, "片假名")
        super().mousePressEvent(event)


class KanaWindow(QWidget):
    """独立五十音窗；打开一次后常驻，关闭只是隐藏。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("五十音图 · RoseSI")
        self.setObjectName("KanaRoot")
        self.setMinimumSize(600, 640)
        self.resize(680, 780)
        self.setStyleSheet(KANA_QSS)
        self._cells: list[KanaCell] = []
        self._build()
        self._always_on_top = False

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        header = QFrame(self)
        header.setObjectName("KanaHeader")
        head = QHBoxLayout(header)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("五十音图", header)
        title.setObjectName("KanaTitle")
        sub = QLabel("左键复制平假名 · 右键复制片假名 · Ctrl+F 搜索", header)
        sub.setObjectName("KanaSub")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        head.addLayout(title_box)
        head.addStretch(1)

        self.top_check = QCheckBox("置顶", header)
        self.top_check.toggled.connect(self._set_always_on_top)
        head.addWidget(self.top_check)
        close = QPushButton("关闭  Esc", header)
        close.setObjectName("KanaClose")
        close.clicked.connect(self.close)
        head.addWidget(close)
        root.addWidget(header)

        self.search = QLineEdit(self)
        self.search.setObjectName("KanaSearch")
        self.search.setPlaceholderText("搜索假名 / 罗马字，例如 き、ki、キ")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        root.addWidget(self.search)

        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)
        self._build_tab("清音 · 46", SEION)
        self._build_tab("浊音 / 半浊音 · 25", DAKUON)
        self._build_tab("拗音 · 33", YOON)

        extras = QHBoxLayout()
        extras.setSpacing(6)
        for hira, kata, romaji in EXTRAS:
            cell = KanaCell(hira, kata, romaji, self, compact=True)
            cell.setFixedWidth(46)
            cell.copied.connect(self._copy)
            extras.addWidget(cell)
            self._cells.append(cell)
        extras.addStretch(1)
        root.addLayout(extras)

        self.status = QLabel("点击任意假名即可复制", self)
        self.status.setObjectName("KanaStatus")
        root.addWidget(self.status)

    def _build_tab(self, title: str, rows: list[list[tuple[str, str, str] | None]]) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget(scroll)
        grid = QGridLayout(body)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        for row_index, row in enumerate(rows):
            for col_index, item in enumerate(row):
                if item is None:
                    spacer = QWidget(body)
                    spacer.setFixedHeight(43)
                    grid.addWidget(spacer, row_index, col_index)
                    continue
                hira, kata, romaji = item
                cell = KanaCell(hira, kata, romaji, body, compact=True)
                cell.copied.connect(self._copy)
                grid.addWidget(cell, row_index, col_index)
                self._cells.append(cell)
        for col in range(5):
            grid.setColumnStretch(col, 1)
        grid.setRowStretch(len(rows), 1)
        scroll.setWidget(body)
        self.tabs.addTab(scroll, title)

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        for cell in self._cells:
            hay = f"{cell.hira} {cell.kata} {cell.romaji}".lower()
            cell.setVisible(not needle or needle in hay)

    def _copy(self, text: str, kind: str) -> None:
        QApplication.clipboard().setText(text)
        self.status.setText(f"已复制 {kind}「{text}」")

    def _set_always_on_top(self, enabled: bool) -> None:
        self._always_on_top = enabled
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.show()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.search.setFocus()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_F:
            self.search.setFocus()
            self.search.selectAll()
            return
        super().keyPressEvent(event)
