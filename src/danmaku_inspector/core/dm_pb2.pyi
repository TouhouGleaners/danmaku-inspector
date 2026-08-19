class DanmakuElem:
    id: int
    progress: int
    mode: int
    fontsize: int
    color: int
    midHash: str
    content: str | None
    ctime: int
    weight: int
    action: str
    pool: int
    idStr: str
    attr: int
    animation: str

class DmSegMobileReply:
    elems: list[DanmakuElem]
    state: int

    def ParseFromString(self, data: bytes) -> None: ...
