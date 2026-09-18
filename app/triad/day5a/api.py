"""Operator-authenticated provider setup. No secret read or arbitrary command endpoint."""

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from triad.api import require_operator
from triad.day5a.contracts import ProviderPolicy
from triad.day5a.control import ProviderControl
from triad.day5a.verification import verify

router = APIRouter(prefix="/api/providers")
AUTH = [Depends(require_operator)]


def service():
    return ProviderControl()


DEP = Depends(service)


class KeyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: SecretStr


class EnableInput(BaseModel):
    enabled: bool


class GrantInput(BaseModel):
    work_item_id: str


class BudgetInput(BaseModel):
    daily_usd: float = Field(ge=0, le=25, allow_inf_nan=False)


@router.post("/api-budget", dependencies=AUTH)
def api_budget(body: BudgetInput, control: ProviderControl = DEP):
    return control.authorize_api_budget(body.daily_usd)


@router.get("")
def dashboard(control: ProviderControl = DEP):
    return control.dashboard()


@router.put("/policy", dependencies=AUTH)
def policy(body: ProviderPolicy, control: ProviderControl = DEP):
    return control.save_policy(body)


@router.post("/{agent}/enabled", dependencies=AUTH)
def enable(agent: str, body: EnableInput, control: ProviderControl = DEP):
    return control.enable(agent, body.enabled)


@router.post("/{agent}/allow-once", dependencies=AUTH)
def allow_once(agent: str, body: GrantInput, control: ProviderControl = DEP):
    return control.allow_once(agent, body.work_item_id)


@router.put("/transports/{transport_id}/credential", dependencies=AUTH)
def credential(transport_id: str, body: KeyInput, control: ProviderControl = DEP):
    return control.set_key(transport_id, body.value.get_secret_value())


@router.delete("/transports/{transport_id}/credential", dependencies=AUTH)
def delete_credential(transport_id: str, control: ProviderControl = DEP):
    return control.delete_key(transport_id)


@router.post("/transports/{transport_id}/refresh", dependencies=AUTH)
def refresh(transport_id: str, control: ProviderControl = DEP):
    return control.refresh(transport_id)


@router.post("/transports/{transport_id}/models", dependencies=AUTH)
def models(transport_id: str, control: ProviderControl = DEP):
    return control.transport(transport_id).list_models()


@router.post("/transports/{transport_id}/test", dependencies=AUTH)
def test(transport_id: str, control: ProviderControl = DEP):
    return verify(control, transport_id)


@router.post("/transports/{transport_id}/workitem", dependencies=AUTH)
def workitem(transport_id: str, control: ProviderControl = DEP):
    return verify(control, transport_id, acceptance=True)


@router.post("/transports/{transport_id}/login", dependencies=AUTH, status_code=202)
def login(transport_id: str, background: BackgroundTasks, control: ProviderControl = DEP):
    adapter = control.transport(transport_id)
    if adapter.transport_type != "CLI" or not adapter.command():
        raise ValueError("Install vendor CLI before login")
    background.add_task(control.authenticate, transport_id)
    return {
        "status": "AUTHENTICATING",
        "instructions": "Complete the vendor browser login. Refresh status afterward.",
    }


@router.post("/transports/{transport_id}/logout", dependencies=AUTH)
def logout(transport_id: str, control: ProviderControl = DEP):
    return control.authenticate(transport_id, logout=True)
