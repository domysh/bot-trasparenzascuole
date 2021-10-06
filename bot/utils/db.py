import random, string, json
from hashlib import sha256
from pymongo import MongoClient, IndexModel, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from datetime import datetime
from base64 import b64encode

MONGO_URL = "mongodb://mongo/"
DB_CONN = MongoClient(MONGO_URL)
DB = DB_CONN["main"]
MANDATORY_TIME_LIMIT = 5
MANDATORY_DIGITS = 6

class JCallbackHash:
    def __init__(self,data=None,hash=None):
        if not data is None:
            self.data = self._parse_data(data)
            self.hash = self._gen_hash(self.data)
            try:
                DB["callback_data_hash"].insert_one({"hash":self.hash, "data":self.data, "created":datetime.now()})
            except DuplicateKeyError:
                DB["callback_data_hash"].update_one({"hash":self.hash},{"$set":{"created":datetime.now()}})
        elif not hash is None:
            self.hash = hash
            self.data = DB["callback_data_hash"].find_one({"hash":self.hash})["data"]
        else:
            raise Exception("Invalid JCallback builder called! insert at least an option")
    
    def json(self):
        return json.loads(self.data)

    def _parse_data(self,data):
        if type(data) == dict:
            return json.dumps(data)
        elif type(data) == str:
            return data
        return None

    def _gen_hash(self,data):
        return b64encode(sha256(self._parse_data(data).encode()).digest()).decode()

def init():
    DB["users"].create_indexes([
        IndexModel([("id",ASCENDING)],unique=True),
        IndexModel([("admin",ASCENDING)])
    ])
    DB["callback_data_hash"].create_indexes([
        IndexModel([("hash",ASCENDING)],unique=True),
        IndexModel([("created",ASCENDING)],expireAfterSeconds=60*60*24*10)
    ])
    DB["mandatory_list"].create_indexes([
        IndexModel([("id",ASCENDING)],unique=True),
        IndexModel([("created",ASCENDING)],expireAfterSeconds=60*MANDATORY_TIME_LIMIT)
    ])
    DB["feed_msg"].create_indexes([
        IndexModel([("match",ASCENDING)],unique=True),
        IndexModel([("created",ASCENDING)],expireAfterSeconds=60*60*24*10)
    ])
    _get_settings()

def gen_digits(n_digits):
    return "".join(random.choices(string.digits,k=n_digits))

def gen_madatory_code():
    return gen_digits(MANDATORY_DIGITS)

def create_mandatory(user):
    code = gen_madatory_code()
    while True:
        try:
            DB["mandatory_list"].insert_one({"id":int(code),"created_by":user.id(),"created":datetime.now()})
            break
        except DuplicateKeyError:
            code = gen_madatory_code()
            continue
    return code

def accept_mandatory(code):
    res = DB["mandatory_list"].find_one_and_delete({"id":int(code)})
    if res is None:
        return False
    else:
        return res["created_by"]


class TelegramUser:

    def __init__(self,id):
        self._id = int(id)

    @classmethod
    def load_telegram(cls, tg_user):
        DB["users"].update_one({"id":int(tg_user.id)},
        {
            "$set":{
                "id":int(tg_user.id),
                "name":tg_user.first_name,
                "surename":tg_user.last_name,
                "username":tg_user.username
            }
        },upsert=True)
        return cls(tg_user.id)

    @classmethod
    def load_by_data(cls,data):
        res = cls(data["id"])
        res._assign_infos(data)
        return res

    def _get_attr_or_load(self,name):
        if hasattr(self, name):
            return getattr(self,name)
        else:
            self._load()
            return getattr(self,name)

    def name(self):
        return self._get_attr_or_load("_name")

    def surename(self):
        return self._get_attr_or_load("_surename")
    
    def username(self):
        return self._get_attr_or_load("_username")
    
    def id(self):
        return self._get_attr_or_load("_id")
        
    def admin(self):
        return self._get_attr_or_load("_admin")

    def _load(self):
        usr = DB["users"].find_one({"id":self.id()})
        if usr is None:
            raise Exception("No user found")
        self._assign_infos(usr)

    def _assign_infos(self,usr):
        self._name = usr["name"]
        self._surename = usr["surename"]
        self._username = usr["username"]
        self._admin = usr["admin"] if "admin" in usr.keys() else None

    def is_admin(self):
        from utils import config as conf
        if self.id() == conf.ADMIN_ID:
            return True
        return not self.admin() is None

    def is_tester(self):
        return "allowMaintenance" in self.permissions() 

    def permissions(self):
        from utils import config as conf
        if self.id() == conf.ADMIN_ID:
            return [ele.id for ele in conf.perms]
        if self.is_admin():
            return self.admin()["permissions"]
        return []

    def _set_permissions(self,perm_list):
        if self.is_admin():
            new_perms = list(set(perm_list))
            new_perms = self.validate_permissions(new_perms)
            DB["users"].update_one({"id":self.id()},{"$set":{"admin.permissions":new_perms}})
            self.admin()["permissions"] = new_perms

    def add_permission(self,perm):
        from utils import config as conf
        if self.id() == conf.ADMIN_ID: return
        self._set_permissions(self.permissions()+[perm])

    def remove_permission(self,perm):
        from utils import config as conf
        if self.id() == conf.ADMIN_ID: return
        self._set_permissions([ele for ele in self.permissions() if ele != perm])


    @staticmethod
    def validate_permissions(perms):
        from utils import config as conf
        existing_perms = [ele.id for ele in conf.perms]
        res = []
        for ele in existing_perms:
            if ele in perms:
                res.append(ele)
        return res
    
    def delete(self):
        DB["users"].delete_one({"id":self.id()})
    
    def set_admin(self):
        if not self.is_admin():
            self._admin = {
                "permissions":[]
            }
            DB["users"].update_one({"id":self.id()},{"$set":{"admin":self.admin()}})
    
    def remove_admin(self):
        if self.is_admin():
            DB["users"].update_one({"id":self.id()},{"$unset":{"admin":""}})
            self._admin = None

    @staticmethod
    def get_all_users():
        for ele in DB["users"].find({}):
            yield TelegramUser.load_by_data(ele)
    
    @staticmethod
    def get_all_admins():
        for ele in DB["users"].find({"admin":{"$exists":True}}):
            yield TelegramUser.load_by_data(ele)
    
    @staticmethod
    def count_users():
        return int(DB["users"].count({}))
    
    @staticmethod
    def count_admins():
        return int(DB["users"].count({"admin":{"$exists":True}}))
    

def index_range(index_from,index_to):
    index_from = int(index_from)
    index_to = int(index_to)
    if index_to < index_from:
        index_from, index_to = index_to, index_from
    return index_from, index_to

def search_transform(s):
    return {"$text":{"$search":" ".join(['"'+ele.strip()+'"' for ele in s.strip().replace('"','').split() if ele.strip() not in ("",None)])}}

class Docs:
    @staticmethod
    def range(index_a,index_b):
        index_a, index_b = index_range(index_a,index_b)
        if index_a < 0 or index_b < 0: return None
        return list(DB["docs"].find({},{"_id":False}).sort("date",ASCENDING)[index_a:index_b])
    
    @staticmethod
    def match(match_id):
        return DB["docs"].find_one({"match":match_id},{"_id":False})
    
    @staticmethod
    def search(str_search):
        for ele in DB["docs"].find(search_transform(str_search),{"_id":False, "match":True}).sort("date",DESCENDING):
            yield ele["match"]

    @staticmethod
    def index(indx):
        indx = int(indx)
        if indx < 0: return None
        return DB["docs"].find({},{"_id":False}).sort("date",ASCENDING)[indx]
    
    @staticmethod
    def length():
        return int(DB["docs"].count_documents({}))

    @staticmethod
    def pids_info():
        return list(DB["pids"].find({},{"_id":False}))

class FeedMsg:

    @staticmethod
    def add_msg_feed(match_id,element):
        if type(element) == list:
            DB["feed_msg"].update_one({"match":match_id},{"$push":{"messages":{"$each":element}}},upsert=True)
        else:    
            DB["feed_msg"].update_one({"match":match_id},{"$push":{"messages":element}},upsert=True)
    
    @staticmethod
    def get_msg_feed(match_id):
        res = DB["feed_msg"].find_one_and_delete({"match":match_id})
        if res is None:
            return []
        else:
            return res["messages"]

class Events:
    @staticmethod
    def update(last_index):
        return list(DB["docs_events"].find({},{"_id":False}).sort("date",ASCENDING)[int(last_index):])
    
    @staticmethod
    def length():
        return int(DB["docs_events"].count_documents({}))



global SETTINGS_CACHE
SETTINGS_CACHE = None
SETTINGS_ID = "tgbot"
DEFAULT_SETTINGS = {
    "id":SETTINGS_ID,
    "maintenance":False
}
def _get_settings():
    global SETTINGS_CACHE
    if SETTINGS_CACHE is None:
        SETTINGS_CACHE = DB["static"].find_one({"id":SETTINGS_ID})
        if SETTINGS_CACHE is None:
            DB["static"].insert_one(DEFAULT_SETTINGS)
            SETTINGS_CACHE = dict(DEFAULT_SETTINGS)
    return SETTINGS_CACHE

def _set_settings(settings):
    _get_settings()
    DB["static"].update_one({"id":SETTINGS_ID},{"$set":settings})

def get_pid_name(pid_id):
    for ele in Docs.pids_info():
        if ele["id"] == pid_id:
            return ele["name"]
    return None


