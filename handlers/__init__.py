from telegram.ext import Application

from . import admin, browse, wizard


def register(app: Application) -> None:
    for h in [*wizard.handlers(), *admin.handlers(), *browse.handlers()]:
        app.add_handler(h)
