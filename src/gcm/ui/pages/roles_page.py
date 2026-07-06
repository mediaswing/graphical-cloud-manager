from gcm.ui.pages.base_page import PlaceholderPage


class RolesPage(PlaceholderPage):
    def __init__(self, parent=None) -> None:
        super().__init__(
            "Roles (RBAC)",
            "Assign built-in and custom Entra directory roles, including "
            "PIM-eligible assignments. Not yet implemented.",
            parent,
        )
