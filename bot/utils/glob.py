from telegram.ext import ConversationHandler, Filters
from functools import wraps
import re, telegram, traceback, datetime

EXCLUDE_CANCEL = Filters.regex(r"^(?!(\\/cancel)$)(.|\\n)+$")
updater = None

def callb(cb:str):
    return "^"+re.escape(cb)+"$"

def t_or_f(v): return "✅" if v else "❌"

def sendmsg(*args,**kargs):
    from utils import config as conf
    try:
        try: return updater.bot.send_message(*args,**kargs)
        except telegram.error.Unauthorized:
            from utils import db
            db.TelegramUser(args[0]).delete()
        except telegram.error.BadRequest:pass
        except Exception as e:
            updater.bot.send_message(int(conf.ADMIN_ID),f"Hey, è stata lanciata una Exception!\nError: {str(e)}\nDa sendmsg_function")
            traceback.print_exc()
    except Exception:pass #This func don't have to raise any kind of exception!

def adminmsg(*args,**kargs):
    from utils import config as conf
    sendmsg(conf.ADMIN_ID,*args,**kargs)

def     msg(merge_to_message:bool = True,
            adm:int = None,
            automatic_answer_query:bool = True,
            log_print:bool = True,
            bypass_maintenance = False,
            context:bool=False,
            jcallb:bool = False):
    from utils import db, config as conf
    context_on = context
    def callable(f):
        @wraps(f)
        def wrap(update, context):
            try:
                user = None
                log_msg = None
                jcallb_data = None
                if update.message is None:
                    user = db.TelegramUser.load_telegram(update.callback_query.from_user)
                    if automatic_answer_query: update.callback_query.answer()
                    if merge_to_message: update.message = update.callback_query
                    if jcallb:
                        jcallb_data = JCallB().parse(update.callback_query.data)
                        if jcallb_data is None:
                            update.message.edit_message_text("Operazione scaduta ⏱️!\nGenera un nuovo messaggio per eseguire l'operazione!")
                            return ConversationHandler.END
                    
                else:
                    if jcallb: raise Exception("It's not possible catch a JCallback is there is no callback data")
                    log_msg = update.message.text
                    user = db.TelegramUser.load_telegram(update.message.from_user)
                if log_print and not log_msg is None:
                    print(f"{datetime.datetime.now()} @{user.username()} - {user.id()} >> '{log_msg}'")
                if conf.settings("maintenance") and not bypass_maintenance:
                    if not user.is_tester():
                        sendmsg(user.id(),
                           "Ops! Mi dispiace ma il bot è in manutenzione! 😢\n"
                                "Il bot rientrerà in funzione il prima possibile!\n"
                                "Puoi usare il comando /contact per contattarmi se ne hai neccesità!")
                        return ConversationHandler.END
                if not adm is None:
                    if user.is_admin():
                        if adm != True:
                            if adm not in user.permissions():
                                sendmsg(user.id(),
                                    "Non hai sufficienti privilegi per eseguire questo comando! 🚫\nIn caso pensi sia un errore contatta il creatore del bot.")
                                return ConversationHandler.END    
                    else:
                        sendmsg(user.id(),
                            "Questo è un comando di amministrazione!\nL'accesso è stato negato! 🚫")
                        return ConversationHandler.END
                params = [update]
                if context_on:
                    params.append(context)
                params.append(user)
                if jcallb:
                    params.append(jcallb_data)
                return f(*params)
            except telegram.error.BadRequest as e:
                if not "Message is not modified" in e.message and\
                    not "Query is too old" in e.message:
                    segnalate_error(e,update)
            except Exception as e:
                segnalate_error(e,update)
        return wrap
    return callable

def segnalate_error(e:Exception,update):
    traceback.print_exc()
    try:
        if update.message is None:
            user = update.callback_query.from_user
        else:
            user = update.message.from_user
        from utils import config as conf
        if conf.SEND_EXCEPTION_ADVICE_TO_ADMIN:
            adminmsg(f"Hey, è stata lanciata una Exception!\nError: {str(e)}\nDa @{user.username} ID: {user.id}")
            sendmsg(user.id,"Ops! Si è verificato un problema! 😱\nIl creatore del bot ha ricevuto già una notifica relativa al problema! 😓\nIl problema verrà risolto al più presto! 👍")
        else:
            sendmsg(user.id,"Ops! Si è verificato un problema! 😱, prova a rieseguire l'operazione!\nIn caso il problema persiste contatta l'amministratore con il comando /contact 😓")
    except Exception as e:
        traceback.print_exc()


@msg()
def cancel_op(update,user):
    update.message.reply_text("Operazione cancellata! ❌")
    return ConversationHandler.END

@msg()
def cancel_op_callback(update,user):
    update.message.edit_message_text("Operazione cancellata! ❌")
    return ConversationHandler.END


"""
callback request use

Because of the telegram limit of the callback_data value, this bot save the informations
in the database (with an expire of 50 days as setted in the index of mongo db).
the elaborated json data is hashed with sha256 and the digest (in hex string format) is sended as callback_data (sending 64 bytes that is also the maximum limit)
When the user send the callback, this will be taken by the program and searched in the db for being "converted" in the string value

This allow to bypass virtualy the limit setted by telegram

This is implemented in the Jcallback Class in utils.db
"""
class JCallB:
    def __init__(self,id=""):
        if "|" in id:
            raise Exception("Invalid character '|' for jcallback")
        if len(id) > 20:
            raise Exception("Max lenght for the callback id length is 20")
        self.__id = id
    
    def id(self):
        return self.__id

    def create(self,data:dict):
        from utils.db import JCallbackHash
        return self.__id.ljust(20,"|")+JCallbackHash(data).hash

    def parse(self,data:str):
        from utils.db import JCallbackHash
        try:
            return JCallbackHash(hash=data[20:]).json()
        except TypeError:
            return None
    
    def regex_filter(self):
        return "^"+re.escape(self.__id.ljust(20,"|"))+"[A-Za-z0-9+/=]{44}$"