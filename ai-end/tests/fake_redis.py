"""进程内 Redis 替身：给不依赖真实 Redis 的 SSE / 会话归属测试用。"""


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.expires = []

    def ping(self):
        return True

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        if ex is not None:
            self.expires.append((key, ex))
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed

    def expire(self, key, ttl):
        self.expires.append((key, ttl))
        return True

    def sadd(self, key, *members):
        bucket = self.store.setdefault(key, set())
        if not isinstance(bucket, set):
            bucket = set()
            self.store[key] = bucket
        bucket.update(members)
        return len(members)

    def sismember(self, key, member):
        bucket = self.store.get(key, set())
        return member in bucket if isinstance(bucket, set) else False

    def rpush(self, key, *values):
        lst = self.store.setdefault(key, [])
        if not isinstance(lst, list):
            lst = []
            self.store[key] = lst
        lst.extend(values)
        return len(lst)

    def lrange(self, key, start, end):
        lst = self.store.get(key) or []
        if not isinstance(lst, list):
            return []
        if end == -1:
            return lst[start:]
        return lst[start : end + 1]

    def llen(self, key):
        lst = self.store.get(key) or []
        return len(lst) if isinstance(lst, list) else 0

    def eval(self, *args, **kwargs):
        raise RuntimeError("lua not supported in FakeRedis")
