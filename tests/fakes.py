"""A fake HTTP layer for python-telegram-bot: every Bot API call is answered locally and recorded.
Nothing ever reaches api.telegram.org, and the token is a dummy."""
import itertools
import json
import time

from telegram.request import BaseRequest

DUMMY_TOKEN = "123456:" + "TESTTOKEN" * 4
BOT_USER = {"id": 123456, "is_bot": True, "first_name": "KDH", "username": "kdrama_heaven_bot"}


class FakeRequest(BaseRequest):
    def __init__(self):
        self.calls = []          # (method, params)
        self.ids = itertools.count(100)
        self.fail_next = {}      # method -> exception json to return once
        self.blocked = set()     # user ids that never started the bot (DM -> 403)

    @property
    def read_timeout(self):
        return 5

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    def of(self, method):
        return [p for m, p in self.calls if m == method]

    async def do_request(self, url, method, request_data=None, **kw):
        api = url.rsplit("/", 1)[-1]
        params = dict(request_data.parameters) if request_data else {}
        for k, v in params.items():
            if isinstance(v, str) and v[:1] in "{[":
                try:
                    params[k] = json.loads(v)
                except ValueError:
                    pass
        self.calls.append((api, params))
        if api in {"sendMessage", "sendPhoto"} and params.get("chat_id") in self.blocked:
            return 403, json.dumps({"ok": False, "error_code": 403,
                                    "description": "Forbidden: bot can't initiate conversation with a user"}).encode()
        if api in self.fail_next:
            err = self.fail_next.pop(api)
            return err.get("error_code", 400), json.dumps(err).encode()
        return 200, json.dumps({"ok": True, "result": self._result(api, params)}).encode()

    def _msg(self, params, **extra):
        chat = params.get("chat_id", 1)
        chat_obj = {"id": chat if isinstance(chat, int) else -1001234567890, "type": "channel" if not isinstance(chat, int) or chat < 0 else "private"}
        return {"message_id": next(self.ids), "date": int(time.time()), "chat": chat_obj, **extra}

    def _result(self, api, p):
        if api == "getMe":
            return BOT_USER
        if api == "sendMessage":
            return self._msg(p, text=p.get("text", ""))
        if api == "sendPhoto":
            return self._msg(p, caption=p.get("caption", ""),
                             photo=[{"file_id": "x", "file_unique_id": "y", "width": 1, "height": 1}])
        if api == "getFile":
            return {"file_id": p.get("file_id", "f"), "file_unique_id": "fu", "file_path": "documents/f.jpg"}
        if api in {"editMessageCaption", "editMessageText", "editMessageReplyMarkup"}:
            return self._msg(p) | {"message_id": p.get("message_id", 1)}
        return True


_uid = itertools.count(1)


def msg_update(text=None, user_id=1, chat_id=None, photo=False, caption=None, reply=None, document=None):
    chat_id = chat_id or user_id
    m = {"message_id": next(_uid), "date": int(time.time()),
         "chat": {"id": chat_id, "type": "private"},
         "from": {"id": user_id, "is_bot": False, "first_name": "U", "username": f"user{user_id}"}}
    if photo:
        m["photo"] = [{"file_id": "small", "file_unique_id": "s", "width": 90, "height": 90},
                      {"file_id": "POSTER_FILE_ID", "file_unique_id": "b", "width": 900, "height": 1200}]
    if photo and photo is not True:
        m["photo"][-1]["file_id"] = photo
    if document:
        m["document"] = {"file_id": document, "file_unique_id": "d", "mime_type": "image/jpeg", "file_name": "p.jpg"}
    if caption is not None:
        m["caption"] = caption
    if reply is not None:
        m["reply_to_message"] = reply["message"]
    if text is not None:
        m["text"] = text
        if text.startswith("/"):
            cmd = text.split()[0]
            m["entities"] = [{"type": "bot_command", "offset": 0, "length": len(cmd)}]
    return {"update_id": next(_uid), "message": m}


def cb_update(data, user_id=1, chat_id=None, message_id=1, chat_type="private"):
    chat_id = chat_id or user_id
    return {"update_id": next(_uid), "callback_query": {
        "id": str(next(_uid)), "chat_instance": "ci", "data": data,
        "from": {"id": user_id, "is_bot": False, "first_name": "U"},
        "message": {"message_id": message_id, "date": int(time.time()), "chat": {"id": chat_id, "type": chat_type},
                    "text": "card"}}}
