import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'scripts'


def load_script(name):
    # `edge_deploy` imports sibling scripts by their normal module names.  Test
    # collection must not depend on some earlier edge test having populated
    # sys.modules or altered sys.path first.
    original_path = sys.path[:]
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        # Imported modules may themselves prepend paths; pop(0) would remove
        # their entry and leave our scripts path behind.
        sys.path[:] = original_path


edge_transaction = load_script('edge_transaction')
edge_runtime = load_script('edge_runtime')
edge_deploy = load_script('edge_deploy')

Config = edge_deploy.Config
Layout = edge_transaction.Layout
SHA = 'a' * 40


def config(root, **overrides):
    values = {
        'root': root,
        'layout': Layout(18000, 15173),
        'blue': (18001, 15174),
        'green': (18002, 15175),
    }
    values.update(overrides)
    return Config(**values)


def clear_environment(monkeypatch):
    names = [
        'PROJECT_ROOT',
        'WEBCOMPILER_ACTIVE_COLOR_FILE',
        'WEBCOMPILER_LEGACY_PROJECT_NAME',
        'WEBCOMPILER_EDGE_NAME',
        'WEBCOMPILER_BACKEND_EDGE_NAME',
        'WEBCOMPILER_FRONTEND_EDGE_NAME',
        'WEBCOMPILER_EDGE_BACKEND_PORT',
        'WEBCOMPILER_EDGE_FRONTEND_PORT',
        'WEBCOMPILER_BLUE_BACKEND_PORT',
        'WEBCOMPILER_BLUE_FRONTEND_PORT',
        'WEBCOMPILER_GREEN_BACKEND_PORT',
        'WEBCOMPILER_GREEN_FRONTEND_PORT',
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_from_environment_accepts_canonical_root_and_default_ports(tmp_path, monkeypatch):
    deploy_root = tmp_path / 'project'
    (deploy_root / '.deploy').mkdir(parents=True)
    clear_environment(monkeypatch)
    monkeypatch.setenv('PROJECT_ROOT', str(deploy_root))

    result = Config.from_environment()

    assert result.root == deploy_root
    assert result.layout == Layout(18000, 15173)
    assert result.blue == (18001, 15174)
    assert result.green == (18002, 15175)
    assert result.edge_name == 'webcompiler-edge-v2'
    assert result.project_prefix == 'webcompiler'
    assert result.legacy_names == (
        'webcompiler-edge-backend',
        'webcompiler-edge-frontend',
        'webcompiler-backend-1',
        'webcompiler-frontend-1',
    )


def test_from_environment_uses_custom_legacy_project_prefix(tmp_path, monkeypatch):
    deploy_root = tmp_path / 'project'
    (deploy_root / '.deploy').mkdir(parents=True)
    clear_environment(monkeypatch)
    monkeypatch.setenv('PROJECT_ROOT', str(deploy_root))
    monkeypatch.setenv('WEBCOMPILER_LEGACY_PROJECT_NAME', 'legacy-stack')

    result = Config.from_environment()

    assert result.legacy_names == (
        'webcompiler-edge-backend',
        'webcompiler-edge-frontend',
        'legacy-stack-backend-1',
        'legacy-stack-frontend-1',
    )


def test_config_matches_production_resource_name_and_path_contract(tmp_path):
    result = config(tmp_path)

    assert result.root.is_absolute()
    assert result.root.resolve() == result.root
    assert result.root / '.deploy' / 'active-color' == tmp_path / '.deploy' / 'active-color'
    assert result.edge_name == 'webcompiler-edge-v2'
    assert result.project_prefix == 'webcompiler'
    assert result.legacy_names == ('webcompiler-edge-backend', 'webcompiler-edge-frontend')


@pytest.mark.parametrize('field,value', [
    ('layout', Layout(18001, 15173)),
    ('layout', Layout(18000, 15174)),
    ('blue', (18000, 15174)),
    ('blue', (18001, 15173)),
    ('green', (18001, 15175)),
    ('green', (18002, 15174)),
])
def test_config_rejects_each_cross_color_port_overlap(tmp_path, field, value):
    with pytest.raises(ValueError, match='distinct'):
        config(tmp_path, **{field: value})


def test_config_rejects_relative_deployment_root():
    with pytest.raises(ValueError, match='non-symlink deployment root'):
        config(Path('relative/project'))


def test_config_rejects_symlinked_deploy_directory(tmp_path, monkeypatch):
    deploy_root = tmp_path / 'project'
    deploy_root.mkdir()
    target = tmp_path / 'deploy-target'
    target.mkdir()
    deploy_link = deploy_root / '.deploy'
    try:
        deploy_link.symlink_to(target, target_is_directory=True)
    except OSError:
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path,
            'is_symlink',
            lambda candidate: candidate == deploy_link or original_is_symlink(candidate),
        )

    with pytest.raises(ValueError, match='non-symlink deployment root'):
        config(deploy_root)


@pytest.mark.parametrize('field,value', [
    ('edge_name', 'WebCompiler-edge'),
    ('project_prefix', 'webcompiler/project'),
    ('legacy_names', ('webcompiler-edge-backend', 'webcompiler edge frontend')),
])
def test_config_rejects_unsafe_resource_name(tmp_path, field, value):
    with pytest.raises(ValueError, match='resource names'):
        config(tmp_path, **{field: value})


def test_release_rejects_invalid_color(tmp_path):
    result = config(tmp_path)

    with pytest.raises(ValueError, match='Invalid color'):
        result.release('red', SHA)


def test_release_rejects_invalid_sha(tmp_path):
    result = config(tmp_path)

    with pytest.raises(ValueError, match='Exact release'):
        result.release('blue', 'A' * 40)


def test_from_environment_rejects_noncanonical_active_color_file(tmp_path, monkeypatch):
    deploy_root = tmp_path / 'project'
    (deploy_root / '.deploy').mkdir(parents=True)
    clear_environment(monkeypatch)
    monkeypatch.setenv('PROJECT_ROOT', str(deploy_root))
    monkeypatch.setenv('WEBCOMPILER_ACTIVE_COLOR_FILE', str(deploy_root / 'active-color'))

    with pytest.raises(ValueError, match='canonical active-color'):
        Config.from_environment()
