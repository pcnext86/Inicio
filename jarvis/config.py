"""Configuração: config.json fica na raiz do projeto (nunca servido), com permissões 600."""
import json
import os
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLACEHOLDERS = ("PUT-YOUR-KEY-HERE", "PUT-A-6-DIGIT-CODE-HERE", "", None)


def config_path():
    return pathlib.Path(os.environ.get("HOLO_CONFIG") or ROOT / "config.json")


def state_dir():
    return pathlib.Path(os.environ.get("HOLO_STATE") or ROOT / "state")


def lock_down(path):
    """Só o teu utilizador lê (chmod 600). No Windows isto é inofensivo."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load():
    try:
        cfg = json.loads(config_path().read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {"_error": "config.json inválido"}
    if "anthropic_api_key" not in cfg and cfg.get("api_key"):
        cfg["anthropic_api_key"] = cfg["api_key"]
    return cfg


def is_real(value):
    return bool(value) and value not in PLACEHOLDERS and not str(value).startswith("PUT-")


def anthropic_key(cfg):
    k = cfg.get("anthropic_api_key")
    return k if is_real(k) else None


def write_json_atomic(path, data):
    """Escrita atómica + chmod 600 depois de cada escrita."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        lock_down(tmp)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    lock_down(path)


def save_section(section, values):
    """Atualiza config.json[section] mantendo o resto. Usado pelo setup_phone.py (idempotente)."""
    p = config_path()
    cfg = json.loads(p.read_text("utf-8")) if p.exists() else {}
    cfg.setdefault(section, {}).update(values)
    write_json_atomic(p, cfg)
    return cfg


def secure_all():
    """No arranque: config.json e ficheiros de estado/tokens a 600."""
    if config_path().exists():
        lock_down(config_path())
    d = state_dir()
    if d.exists():
        for f in d.iterdir():
            if f.is_file():
                lock_down(f)
