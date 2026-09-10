"""A deployment incarnation is not a release SHA or a worker process ID."""
import re
from dataclasses import dataclass


def validate_runtime_id(value, *, allow_empty=False):
    if allow_empty and value == '':
        return value
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value) or value == '0'*32:
        raise ValueError('An exact nonzero runtime instance ID is required')
    return value


@dataclass(frozen=True)
class RuntimeIdentity:
    id: str
    pool_id: str
    deployment_sha: str
    sandbox_pool_id: str

    def __post_init__(self):
        validate_runtime_id(self.id)
        for name in (self.pool_id,self.sandbox_pool_id):
            if not isinstance(name,str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}',name):
                raise ValueError('Invalid runtime pool identity')
        if not isinstance(self.deployment_sha,str) or (self.deployment_sha and
                not re.fullmatch('[a-f0-9]{40}',self.deployment_sha)):
            raise ValueError('Invalid runtime release identity')

    @classmethod
    def configured(cls):
        from app.core.config import settings
        return cls(settings.RUNTIME_INSTANCE_ID,settings.RUNTIME_POOL_ID,
                   settings.DEPLOYMENT_SHA,settings.SANDBOX_POOL_ID)
