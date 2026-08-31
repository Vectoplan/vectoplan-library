import json
from pathlib import Path
import pytest
from src.library.validation.library_package_validator import validate_library_documents

ROOT=Path(__file__).resolve().parents[1]/'src/library/source'


@pytest.mark.parametrize('relative',['hochbau/waende/lod2_aussenwand','haustechnik/energie/photovoltaik/pv_dachanlage'])
def test_packages_pass_canonical_validator(relative):
    root=ROOT/relative
    docs={p.relative_to(root).as_posix():json.loads(p.read_text(encoding='utf-8')) for p in root.rglob('*.json')}
    result=validate_library_documents(docs,package_root=root)
    payload=result.to_dict()
    assert payload.get('is_valid',payload.get('valid')),payload


def test_wall_and_solar_dimensions_have_explicit_units_and_no_executable_generator():
    wall=json.loads((ROOT/'hochbau/waende/lod2_aussenwand/editor/placement.json').read_text())
    assert wall['editor_block']['cell_size']=={'x':1,'y':1,'z':1,'unit':'m'}
    solar=json.loads((ROOT/'haustechnik/energie/photovoltaik/pv_dachanlage/dynamic/generator.json').read_text())
    assert solar['engine']=='roof-solar-layout.v1' and solar['executable_code'] is False
    assert 0<solar['module']['widthM']<3 and solar['module']['powerWp']==450
    assert len(solar['modules']) >= 3
    assert len({module['variantId'] for module in solar['modules']}) == len(solar['modules'])
    assert all(400 <= module['powerWp'] <= 500 and module['sourceUrl'].startswith('https://') for module in solar['modules'])
    assert solar['moduleGapM'] == 0.02 and solar['edgeMarginM'] == 0.3
    assert solar['economics']['electricityPriceEurPerKwh'] == 0.3869
    compensation=solar['economics']['feedInCompensation']
    assert compensation['effectiveFrom']=='2026-08-01' and compensation['effectiveTo']=='2027-01-31'
    assert compensation['fixedSurplusTariffEurPerKwh'][-1]==[100,0.0544]
    assert compensation['directMarketingValueEurPerKwh'][-1]==[1000,0.0584]
