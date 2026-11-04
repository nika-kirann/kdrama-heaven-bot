from telegram.ext import Application, TypeHandler
from telegram import Update

from . import admin, browse, wizard


def register(app: Application) -> None:
    app.add_handler(TypeHandler(Update, browse.track_user), group=-1)
    for h in [*wizard.handlers(), *admin.handlers(), *browse.handlers()]:
        app.add_handler(h)
