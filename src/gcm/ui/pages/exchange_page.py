from gcm.ui.pages.base_page import PlaceholderPage


class ExchangePage(PlaceholderPage):
    def __init__(self, parent=None) -> None:
        super().__init__(
            "Exchange",
            "Mailbox settings via Graph, plus mail-flow rules and litigation "
            "hold via the optional Exchange Online PowerShell bridge. Not yet "
            "implemented.",
            parent,
        )
