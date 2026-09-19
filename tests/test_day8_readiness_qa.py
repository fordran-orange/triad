"""Independent Day 8 readiness adversarial tests; offline archive and real QA gate."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_readiness import service
from trading_core.integrations import readiness as module
from trading_core.intelligence.contracts import ImplementationRun, QARun


def attest(ready, request, manifest, *, mutate=None):
    payload = {
        'request_hash': module.request_key(request),
        'dataset_hash': module.fingerprint(manifest.model_dump(mode='json')),
        'policy': module.POLICY,
        'executed_at': '2026-09-19T12:00:00Z',
        'normalizer_version': 'v2',
        'outlier_method': 'Source comparison',
        'outlier_parameters': {'all_observed_bars': True},
        'outlier_reference_evidence': ['fixture:source-comparison'],
        'outlier_findings': [],
        'outlier_disposition': 'No unresolved findings',
        'critical_findings': [],
        'checks': {c: {'status': 'COMPLETED', 'result': 'PASS', 'evidence': ['offline-check:'+c]} for c in module.CHECKS},
    }
    if mutate:
        mutate(payload)
    digest = module.fingerprint(payload)
    build = ImplementationRun(owner='core', builder='builder', provider='host', model='offline', transport='host', base_commit='base', change_commit='current', files=('fixture',), tests=('independent fixture checks',), evidence=('fixture',))
    qa = QARun(implementation_run_id=build.implementation_run_id, qa_agent='independent-reviewer', qa_provider='host', qa_model='offline', reviewed_commit='current', agent_capabilities_used=('data analysis',), tests_repeated=('offline independent reproduction',), evidence=('readiness:'+digest,), decision='PASS', execution_mode='HOST_INDEPENDENT_QA')
    b={**build.model_dump(mode='json'),'id':build.implementation_run_id,'kind':'ImplementationRun','owner':'core'}
    q={**qa.model_dump(mode='json'),'id':qa.qa_run_id,'kind':'QARun','owner':'core'}
    e={**payload,'id':'readiness-evidence','kind':'ReadinessEvidence','owner':'core','digest':digest,'implementation_id':b['id'],'commit':'current','qa_id':q['id']}
    rows={'ReadinessEvidence':[e],'QARun':[q]}
    ready.records=SimpleNamespace(get=lambda ident,conn=None: b, list=lambda kind,conn=None: rows.get(kind,[]))
    return e,q,rows


def test_exact_reviewed_evidence_allows_fixture_ready_without_strategy_claim(tmp_path,monkeypatch):
    ready,req,_,manifest=service(tmp_path,monkeypatch)
    attest(ready,req,manifest)
    result=ready.evaluate(req)
    assert result['status']=='READY'
    assert result['dataset']['mode']=='FIXTURE'
    assert result['strategy_status']=='NOT_EVALUATED'


@pytest.mark.parametrize('attack',['product_owner','digest_tamper','different_request','stale_commit','latest_rejected','self_review','fixture_execution'])
def test_invalid_review_never_passes(tmp_path,monkeypatch,attack):
    ready,req,_,manifest=service(tmp_path,monkeypatch)
    e,q,rows=attest(ready,req,manifest)
    if attack=='product_owner': e['owner']='triad'
    if attack=='digest_tamper': e['normalizer_version']='changed'
    if attack=='different_request': req=req.model_copy(update={'universe':'Different membership'})
    if attack=='stale_commit': q['reviewed_commit']='old'
    if attack=='latest_rejected': rows['QARun'].append({**q,'id':'rejected','decision':'REJECT'})
    if attack=='self_review': q['qa_agent']='builder'
    if attack=='fixture_execution': q['execution_mode']='TEST_FIXTURE'
    assert ready.reviewed_checks(req,manifest) is None


def test_malformed_host_check_returns_readable_nonready_http_result(tmp_path,monkeypatch):
    ready,req,_,manifest=service(tmp_path,monkeypatch)
    attest(ready,req,manifest,mutate=lambda p:p['checks'].update({'outlier_review':None}))
    import trading_core.api  # Initialize the application's supported import order.
    from trading_core.integrations.api import router,access
    def injected(self,unused=None):
        self.access=ready.access
        self.records=ready.records
    monkeypatch.setattr(module.Readiness,'__init__',injected)
    app=FastAPI();app.include_router(router);app.dependency_overrides[access]=lambda:ready.access
    with TestClient(app,raise_server_exceptions=False) as client:
        response=client.post('/api/core/research-readiness/evaluate',json=req.model_dump(mode='json'))
    assert response.status_code==200
    assert response.json()['status']!='READY'


@pytest.mark.parametrize('defect',['invalid_execution_time','missing_outlier_details'])
def test_incomplete_definition_evidence_cannot_claim_ready(tmp_path,monkeypatch,defect):
    ready,req,_,manifest=service(tmp_path,monkeypatch)
    def modify(payload):
        if defect=='invalid_execution_time': payload['executed_at']='not-a-timestamp'
        else:
            for key in ('outlier_parameters','outlier_reference_evidence','outlier_findings','outlier_disposition'):
                payload.pop(key)
    attest(ready,req,manifest,mutate=modify)
    assert ready.reviewed_checks(req,manifest) is None


def test_unavailable_source_capability_cannot_claim_ready(tmp_path,monkeypatch):
    ready,req,_,manifest=service(tmp_path,monkeypatch)
    attest(ready,req,manifest)
    original=deepcopy(ready.access.registry.catalog()[0])
    original.update(status='UNAVAILABLE',capabilities={'HISTORICAL_BARS':'UNAVAILABLE'})
    ready.access.registry.catalog=lambda:[original]
    assert ready.evaluate(req)['status']=='BLOCKED'


@pytest.mark.parametrize("owner",["triad","aegis","p2p"])
def test_product_cannot_append_canonical_readiness_attestation(owner):
    from trading_core.intelligence.records import Records
    from trading_core.store import Store
    with pytest.raises(PermissionError):
        Records(Store(settings=SimpleNamespace(),scope=owner)).append("ReadinessEvidence",{},owner=owner)
