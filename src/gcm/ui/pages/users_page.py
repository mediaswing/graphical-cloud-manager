from gcm.ui.pages.base_page import PlaceholderPage


class UsersPage(PlaceholderPage):
    def __init__(self, parent=None) -> None:
        super().__init__(
            "Users",
            "List, create, edit, disable, and delete Entra users. Not yet implemented.",
            parent,
        )
