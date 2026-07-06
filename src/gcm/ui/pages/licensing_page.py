from gcm.ui.pages.base_page import PlaceholderPage


class LicensingPage(PlaceholderPage):
    def __init__(self, parent=None) -> None:
        super().__init__(
            "Licensing",
            "View subscribed SKU consumption and assign or remove licenses per "
            "user or group. Not yet implemented.",
            parent,
        )
