"""Default-deny business writes, including GET-side cache and background writes."""
from release_control import writer, validate, permit, request_path, ReleaseBlocked

WRITES = {"insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one", "delete_many",
          "find_one_and_update", "find_one_and_replace", "find_one_and_delete", "bulk_write", "create_index",
          "create_indexes", "drop_index", "drop_indexes", "drop", "rename"}
SECURITY_COLLECTIONS = {"users", "login_attempts", "revoked_tokens", "password_reset_tokens", "auth_events"}


class GuardedCollection:
    def __init__(self, database, collection):
        self.database, self.raw = database, collection

    def __getattr__(self, name):
        if name in WRITES:
            async def write(*args, **kwargs):
                return await self.database.perform(self.raw.name, name, getattr(self.raw, name), *args, **kwargs)
            return write
        return getattr(self.raw, name)

    def with_options(self, *args, **kwargs):
        return GuardedCollection(self.database, self.raw.with_options(*args, **kwargs))

    def aggregate(self, pipeline, *args, **kwargs):
        if any("$out" in p or "$merge" in p for p in pipeline):
            raise ReleaseBlocked("write_aggregation_requires_explicit_operation")
        return self.raw.aggregate(pipeline, *args, **kwargs)


class GuardedDatabase:
    def __init__(self, raw):
        self.raw, self.name = raw, raw.name

    def __getitem__(self, name):
        return GuardedCollection(self, self.raw[name])

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def get_collection(self, name, *args, **kwargs):
        return GuardedCollection(self, self.raw.get_collection(name, *args, **kwargs))

    async def list_collection_names(self, *args, **kwargs):
        return await self.raw.list_collection_names(*args, **kwargs)

    async def command(self, command, *args, **kwargs):
        op = command if isinstance(command, str) else next(iter(command))
        if op in {"ping", "dbStats", "collStats", "listIndexes", "listCollections"}:
            return await self.raw.command(command, *args, **kwargs)
        return await self.perform("$database", op, self.raw.command, command, *args, **kwargs)

    async def create_collection(self, *args, **kwargs):
        return await self.perform("$database", "create_collection", self.raw.create_collection, *args, **kwargs)

    async def perform(self, collection, method, operation, *args, **kwargs):
        if collection == "release_control":
            raise ReleaseBlocked("control_plane_requires_authorized_transition")
        p = permit.get()
        if p and p["database"] == self.name:
            await validate(self, p)
            if p["purpose"] == "security" and collection not in SECURITY_COLLECTIONS:
                raise ReleaseBlocked("security_permit_cannot_mutate_business_data")
            if (collection == "$database" or method in {"drop", "drop_index", "drop_indexes", "create_index", "create_indexes", "rename", "create_collection"}) and not p["purpose"].startswith("maintenance:"):
                raise ReleaseBlocked("schema_change_requires_maintenance_operation")
            return await operation(*args, **kwargs)
        path = request_path.get()
        security = path in {"/api/auth/login", "/api/auth/logout", "/api/auth/refresh"}
        if security and collection in SECURITY_COLLECTIONS:
            async with writer(self, "security"):
                return await operation(*args, **kwargs)
        raise ReleaseBlocked("no_explicit_writer_permit")