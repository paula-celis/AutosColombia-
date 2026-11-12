from datetime import date, datetime
from pathlib import Path
import sqlite3
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Autos Colombia", version="2.0")
BASE_DATOS = Path(__file__).with_name("autos_colombia.db")
TIPOS_VEHICULO = {"carro", "moto"}
TIPOS_CELDA = {"carro", "moto", "mixta"}


def conectar():
    conexion = sqlite3.connect(BASE_DATOS)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def columnas(conexion, tabla):
    return {fila["name"] for fila in conexion.execute(f"PRAGMA table_info({tabla})")}


def crear_tablas():
    """Crea el modelo normalizado y migra el esquema textual de la Iteración 1."""
    conexion = conectar()
    try:
        conexion.execute("""CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            documento TEXT NOT NULL UNIQUE,
            nombres TEXT NOT NULL,
            apellidos TEXT NOT NULL,
            telefono TEXT,
            correo TEXT UNIQUE,
            activo INTEGER NOT NULL DEFAULT 1 CHECK(activo IN (0,1)),
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        conexion.execute("""CREATE TABLE IF NOT EXISTS operadores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL COLLATE NOCASE UNIQUE,
            activo INTEGER NOT NULL DEFAULT 1 CHECK(activo IN (0,1)),
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        conexion.execute("""CREATE TABLE IF NOT EXISTS celdas (
            codigo TEXT PRIMARY KEY,
            tipo TEXT NOT NULL CHECK(tipo IN ('carro','moto','mixta')),
            piso TEXT,
            activa INTEGER NOT NULL DEFAULT 1 CHECK(activa IN (0,1))
        )""")
        conexion.execute("""CREATE TABLE IF NOT EXISTS mensualidades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
            fecha_inicio TEXT NOT NULL,
            fecha_fin TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'pendiente' CHECK(estado IN ('pagada','pendiente')),
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK(fecha_fin >= fecha_inicio)
        )""")
        conexion.execute("""CREATE TABLE IF NOT EXISTS vehiculos (
            placa TEXT PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id) ON DELETE RESTRICT,
            tipo TEXT NOT NULL DEFAULT 'carro' CHECK(tipo IN ('carro','moto'))
        )""")
        vehicle_cols = columnas(conexion, "vehiculos")
        if "usuario_id" not in vehicle_cols:
            conexion.execute("ALTER TABLE vehiculos ADD COLUMN usuario_id INTEGER REFERENCES usuarios(id)")
        if "tipo" not in vehicle_cols:
            conexion.execute("ALTER TABLE vehiculos ADD COLUMN tipo TEXT NOT NULL DEFAULT 'carro'")

        old_cols = columnas(conexion, "estancias") if conexion.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='estancias'"
        ).fetchone() else set()
        if "celda" in old_cols and "celda_codigo" not in old_cols:
            exists_legacy = conexion.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='estancias_legacy'"
            ).fetchone()
            if not exists_legacy:
                conexion.execute("ALTER TABLE estancias RENAME TO estancias_legacy")
            else:
                raise RuntimeError("La migración anterior está incompleta; conserva la base y revisa estancias_legacy")

        conexion.execute("""CREATE TABLE IF NOT EXISTS estancias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehiculo_placa TEXT NOT NULL REFERENCES vehiculos(placa) ON DELETE RESTRICT,
            celda_codigo TEXT NOT NULL REFERENCES celdas(codigo) ON DELETE RESTRICT,
            operador_entrada_id INTEGER NOT NULL REFERENCES operadores(id) ON DELETE RESTRICT,
            operador_salida_id INTEGER REFERENCES operadores(id) ON DELETE RESTRICT,
            fecha_entrada TEXT NOT NULL,
            fecha_salida TEXT,
            CHECK(fecha_salida IS NULL OR fecha_salida >= fecha_entrada),
            CHECK((fecha_salida IS NULL) = (operador_salida_id IS NULL))
        )""")

        legacy_exists = conexion.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='estancias_legacy'"
        ).fetchone()
        migration_done = conexion.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='migraciones'"
        ).fetchone()
        conexion.execute("CREATE TABLE IF NOT EXISTS migraciones (version INTEGER PRIMARY KEY, aplicada_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        applied = conexion.execute("SELECT 1 FROM migraciones WHERE version=2").fetchone()
        if legacy_exists and not applied:
            rows = conexion.execute("SELECT * FROM estancias_legacy ORDER BY id").fetchall()
            for row in rows:
                codigo = (row["celda"] or "CELDA-LEGADA-" + str(row["id"])).strip().upper()
                conexion.execute("INSERT OR IGNORE INTO celdas(codigo,tipo,piso) VALUES(?, 'mixta', 'Legado')", (codigo,))
                def operador_id(nombre, fallback):
                    valor = (nombre or "").strip() or fallback
                    conexion.execute("INSERT OR IGNORE INTO operadores(nombre) VALUES(?)", (valor,))
                    return conexion.execute("SELECT id FROM operadores WHERE nombre=? COLLATE NOCASE", (valor,)).fetchone()["id"]
                op_ent = operador_id(row["operador_entrada"], "Operador legado sin identificar #" + str(row["id"]))
                op_sal = operador_id(row["operador_salida"], "Operador legado sin identificar #" + str(row["id"])) if row["operador_salida"] else None
                conexion.execute("""INSERT OR IGNORE INTO estancias
                    (id,vehiculo_placa,celda_codigo,operador_entrada_id,operador_salida_id,fecha_entrada,fecha_salida)
                    VALUES(?,?,?,?,?,?,?)""",
                    (row["id"], row["placa"], codigo, op_ent, op_sal, row["fecha_entrada"], row["fecha_salida"]))
            conexion.execute("INSERT INTO migraciones(version) VALUES(2)")

        conexion.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_estancia_abierta_vehiculo ON estancias(vehiculo_placa) WHERE fecha_salida IS NULL")
        conexion.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_estancia_abierta_celda ON estancias(celda_codigo) WHERE fecha_salida IS NULL")
        conexion.execute("CREATE INDEX IF NOT EXISTS ix_mensualidad_vigencia ON mensualidades(usuario_id,estado,fecha_inicio,fecha_fin)")
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


crear_tablas()


class UsuarioNuevo(BaseModel):
    documento: str
    nombres: str
    apellidos: str
    telefono: Optional[str] = None
    correo: Optional[str] = None


class UsuarioCambios(BaseModel):
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    telefono: Optional[str] = None
    correo: Optional[str] = None


class OperadorNuevo(BaseModel):
    nombre: str


class CeldaNueva(BaseModel):
    codigo: str
    tipo: str
    piso: Optional[str] = None


class CeldaCambios(BaseModel):
    tipo: Optional[str] = None
    piso: Optional[str] = None
    activa: Optional[bool] = None


class VehiculoNuevo(BaseModel):
    placa: str
    usuario_id: int
    tipo: str


class MensualidadNueva(BaseModel):
    usuario_id: int
    fecha_inicio: str
    fecha_fin: str
    estado: str = "pendiente"


class VehiculoCambios(BaseModel):
    usuario_id: int
    tipo: str


class EntradaNueva(BaseModel):
    placa: str
    celda_codigo: str
    operador_entrada_id: int


class SalidaNueva(BaseModel):
    operador_salida_id: int


def placa_normalizada(placa):
    return "".join((placa or "").upper().split())


def texto_obligatorio(valor, etiqueta):
    limpio = (valor or "").strip()
    if not limpio:
        raise HTTPException(status_code=422, detail=f"{etiqueta} es obligatorio")
    return limpio


def fecha_iso(valor, etiqueta):
    try:
        return date.fromisoformat(valor).isoformat()
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{etiqueta} debe tener formato AAAA-MM-DD")


@app.get("/")
def inicio():
    return FileResponse(Path(__file__).with_name("index.html"))


@app.get("/usuarios")
def listar_usuarios(incluir_inactivos: bool = False):
    with conectar() as db:
        sql = "SELECT id,documento,nombres,apellidos,telefono,correo,activo,creado_en FROM usuarios"
        if not incluir_inactivos:
            sql += " WHERE activo=1"
        return [dict(r) for r in db.execute(sql + " ORDER BY apellidos,nombres")]


@app.post("/usuarios", status_code=201)
def registrar_usuario(datos: UsuarioNuevo):
    documento = "".join(texto_obligatorio(datos.documento, "Documento").upper().split())
    nombres = texto_obligatorio(datos.nombres, "Nombres")
    apellidos = texto_obligatorio(datos.apellidos, "Apellidos")
    correo = datos.correo.strip().lower() if datos.correo and datos.correo.strip() else None
    telefono = datos.telefono.strip() if datos.telefono and datos.telefono.strip() else None
    try:
        with conectar() as db:
            cur = db.execute("INSERT INTO usuarios(documento,nombres,apellidos,telefono,correo) VALUES(?,?,?,?,?)",
                             (documento,nombres,apellidos,telefono,correo))
            return {"mensaje":"Usuario registrado","id":cur.lastrowid,"documento":documento}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="El documento o correo ya está registrado")


@app.put("/usuarios/{usuario_id}")
def actualizar_usuario(usuario_id: int, datos: UsuarioCambios):
    campos = {}
    for clave, valor in datos.dict(exclude_unset=True).items():
        if valor is None:
            continue
        limpio = valor.strip() if isinstance(valor, str) else valor
        if clave in {"nombres", "apellidos"} and not limpio:
            raise HTTPException(status_code=422, detail=f"{clave.capitalize()} no puede estar vacío")
        campos[clave] = limpio or None if isinstance(limpio, str) else limpio
    if not campos:
        raise HTTPException(status_code=422, detail="Envía al menos un campo válido para actualizar")
    if campos.get("correo"):
        campos["correo"] = campos["correo"].lower()
    try:
        with conectar() as db:
            if not db.execute("SELECT 1 FROM usuarios WHERE id=? AND activo=1",(usuario_id,)).fetchone():
                raise HTTPException(status_code=404,detail="Usuario no encontrado o inactivo")
            db.execute("UPDATE usuarios SET " + ",".join(f"{k}=?" for k in campos) + " WHERE id=?",(*campos.values(),usuario_id))
            return {"mensaje":"Usuario actualizado","id":usuario_id}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409,detail="El correo ya pertenece a otro usuario")


@app.delete("/usuarios/{usuario_id}")
def desactivar_usuario(usuario_id: int):
    with conectar() as db:
        cur=db.execute("UPDATE usuarios SET activo=0 WHERE id=? AND activo=1",(usuario_id,))
        if not cur.rowcount:
            raise HTTPException(status_code=404,detail="Usuario no encontrado o ya inactivo")
        return {"mensaje":"Usuario desactivado","id":usuario_id}


@app.get("/operadores")
def listar_operadores(incluir_inactivos: bool = False):
    with conectar() as db:
        sql="SELECT id,nombre,activo FROM operadores"
        if not incluir_inactivos: sql += " WHERE activo=1"
        return [dict(r) for r in db.execute(sql+" ORDER BY nombre")]


@app.post("/operadores", status_code=201)
def registrar_operador(datos: OperadorNuevo):
    nombre=texto_obligatorio(datos.nombre,"Nombre del operador")
    try:
        with conectar() as db:
            cur=db.execute("INSERT INTO operadores(nombre) VALUES(?)",(nombre,))
            return {"mensaje":"Operador registrado","id":cur.lastrowid,"nombre":nombre}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409,detail="El operador ya está registrado")


@app.delete("/operadores/{operador_id}")
def desactivar_operador(operador_id: int):
    with conectar() as db:
        cur=db.execute("UPDATE operadores SET activo=0 WHERE id=? AND activo=1",(operador_id,))
        if not cur.rowcount:
            raise HTTPException(status_code=404,detail="Operador no encontrado o inactivo")
        return {"mensaje":"Operador desactivado","id":operador_id}


@app.get("/celdas")
def listar_celdas(incluir_inactivas: bool = False):
    sql="""SELECT c.codigo,c.tipo,c.piso,c.activa,
       CASE WHEN e.id IS NULL THEN 'Disponible' ELSE 'Ocupada' END AS estado
       FROM celdas c LEFT JOIN estancias e ON e.celda_codigo=c.codigo AND e.fecha_salida IS NULL"""
    if not incluir_inactivas: sql += " WHERE c.activa=1"
    with conectar() as db:
        return [dict(r) for r in db.execute(sql+" ORDER BY c.piso,c.codigo")]


@app.post("/celdas", status_code=201)
def registrar_celda(datos: CeldaNueva):
    codigo=texto_obligatorio(datos.codigo,"Código de celda").upper()
    tipo=texto_obligatorio(datos.tipo,"Tipo de celda").lower()
    if tipo not in TIPOS_CELDA:
        raise HTTPException(status_code=422,detail="El tipo debe ser carro, moto o mixta")
    piso=datos.piso.strip() if datos.piso and datos.piso.strip() else None
    try:
        with conectar() as db:
            db.execute("INSERT INTO celdas(codigo,tipo,piso) VALUES(?,?,?)",(codigo,tipo,piso))
            return {"mensaje":"Celda registrada","codigo":codigo}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409,detail="El código de celda ya existe")


@app.put("/celdas/{codigo}")
def actualizar_celda(codigo: str, datos: CeldaCambios):
    codigo=texto_obligatorio(codigo,"Código de celda").upper()
    campos=datos.dict(exclude_unset=True)
    if not campos:
        raise HTTPException(status_code=422,detail="Envía al menos un campo para actualizar")
    if "tipo" in campos and campos["tipo"] not in TIPOS_CELDA:
        raise HTTPException(status_code=422,detail="Tipo de celda inválido")
    if "piso" in campos and campos["piso"] is not None:
        campos["piso"]=campos["piso"].strip() or None
    with conectar() as db:
        if not db.execute("SELECT 1 FROM celdas WHERE codigo=?",(codigo,)).fetchone():
            raise HTTPException(status_code=404,detail="Celda no encontrada")
        abiertas = db.execute("SELECT v.tipo FROM estancias e JOIN vehiculos v ON v.placa=e.vehiculo_placa WHERE e.celda_codigo=? AND e.fecha_salida IS NULL",(codigo,)).fetchall()
        if campos.get("activa") is False and abiertas:
            raise HTTPException(status_code=409,detail="No se puede desactivar una celda ocupada")
        nuevo_tipo = campos.get("tipo")
        if nuevo_tipo and any(nuevo_tipo not in {r["tipo"], "mixta"} for r in abiertas):
            raise HTTPException(status_code=409,detail="El tipo nuevo no es compatible con el vehículo que ocupa la celda")
        db.execute("UPDATE celdas SET " + ",".join(f"{k}=?" for k in campos) + " WHERE codigo=?",(*campos.values(),codigo))
        return {"mensaje":"Celda actualizada","codigo":codigo}


@app.delete("/celdas/{codigo}")
def desactivar_celda(codigo: str):
    codigo=texto_obligatorio(codigo,"Código de celda").upper()
    with conectar() as db:
        if db.execute("SELECT 1 FROM estancias WHERE celda_codigo=? AND fecha_salida IS NULL",(codigo,)).fetchone():
            raise HTTPException(status_code=409,detail="No se puede desactivar una celda ocupada")
        cur=db.execute("UPDATE celdas SET activa=0 WHERE codigo=? AND activa=1",(codigo,))
        if not cur.rowcount:
            raise HTTPException(status_code=404,detail="Celda no encontrada o inactiva")
        return {"mensaje":"Celda desactivada","codigo":codigo}


@app.get("/mensualidades")
def listar_mensualidades():
    with conectar() as db:
        return [dict(r) for r in db.execute("""SELECT m.id,m.usuario_id,u.documento,
            u.nombres || ' ' || u.apellidos AS usuario,m.fecha_inicio,m.fecha_fin,m.estado
            FROM mensualidades m JOIN usuarios u ON u.id=m.usuario_id ORDER BY m.fecha_fin DESC""")]


@app.post("/mensualidades", status_code=201)
def registrar_mensualidad(datos: MensualidadNueva):
    inicio=fecha_iso(datos.fecha_inicio,"Fecha de inicio")
    fin=fecha_iso(datos.fecha_fin,"Fecha de fin")
    if fin < inicio:
        raise HTTPException(status_code=422,detail="La fecha final no puede ser anterior a la inicial")
    estado=datos.estado.strip().lower()
    if estado not in {"pagada","pendiente"}:
        raise HTTPException(status_code=422,detail="El estado debe ser pagada o pendiente")
    with conectar() as db:
        usuario=db.execute("SELECT activo FROM usuarios WHERE id=?",(datos.usuario_id,)).fetchone()
        if usuario is None or not usuario["activo"]:
            raise HTTPException(status_code=404,detail="El cliente no existe o está inactivo")
        cur=db.execute("INSERT INTO mensualidades(usuario_id,fecha_inicio,fecha_fin,estado) VALUES(?,?,?,?)",
                       (datos.usuario_id,inicio,fin,estado))
        return {"mensaje":"Mensualidad registrada","id":cur.lastrowid,"estado":estado}


@app.post("/vehiculos", status_code=201)
def registrar_vehiculo(datos: VehiculoNuevo):
    placa=placa_normalizada(texto_obligatorio(datos.placa,"Placa"))
    tipo=texto_obligatorio(datos.tipo,"Tipo de vehículo").lower()
    if tipo not in TIPOS_VEHICULO:
        raise HTTPException(status_code=422,detail="El tipo de vehículo debe ser carro o moto")
    with conectar() as db:
        usuario=db.execute("SELECT activo FROM usuarios WHERE id=?",(datos.usuario_id,)).fetchone()
        if usuario is None or not usuario["activo"]:
            raise HTTPException(status_code=422,detail="Selecciona un cliente activo")
        try:
            db.execute("INSERT INTO vehiculos(placa,usuario_id,tipo) VALUES(?,?,?)",(placa,datos.usuario_id,tipo))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409,detail="La placa ya está registrada")
        return {"mensaje":"Vehículo registrado","placa":placa,"usuario_id":datos.usuario_id,"tipo":tipo}


@app.put("/vehiculos/{placa}")
def actualizar_vehiculo(placa: str, datos: VehiculoCambios):
    placa = placa_normalizada(placa)
    tipo = texto_obligatorio(datos.tipo, "Tipo de vehículo").lower()
    if tipo not in TIPOS_VEHICULO:
        raise HTTPException(status_code=422, detail="El tipo de vehículo debe ser carro o moto")
    with conectar() as db:
        if not db.execute("SELECT 1 FROM vehiculos WHERE placa=?", (placa,)).fetchone():
            raise HTTPException(status_code=404, detail="Vehículo no registrado")
        usuario = db.execute("SELECT activo FROM usuarios WHERE id=?", (datos.usuario_id,)).fetchone()
        if usuario is None or not usuario["activo"]:
            raise HTTPException(status_code=422, detail="Selecciona un cliente activo")
        db.execute("UPDATE vehiculos SET usuario_id=?, tipo=? WHERE placa=?", (datos.usuario_id, tipo, placa))
        return {"mensaje": "Vehículo asociado al cliente", "placa": placa, "usuario_id": datos.usuario_id, "tipo": tipo}


@app.get("/vehiculos")
def listar_vehiculos():
    with conectar() as db:
        return [dict(r) for r in db.execute("""SELECT v.placa,v.tipo,v.usuario_id,
            COALESCE(u.nombres || ' ' || u.apellidos,'Sin cliente asignado') AS usuario,
            EXISTS(SELECT 1 FROM estancias e WHERE e.vehiculo_placa=v.placa AND e.fecha_salida IS NULL) AS estancia_abierta
            FROM vehiculos v LEFT JOIN usuarios u ON u.id=v.usuario_id ORDER BY v.placa""")]


@app.post("/entradas", status_code=201)
def registrar_entrada(datos: EntradaNueva):
    placa=placa_normalizada(texto_obligatorio(datos.placa,"Placa"))
    codigo=texto_obligatorio(datos.celda_codigo,"Código de celda").upper()
    hoy=date.today().isoformat()
    with conectar() as db:
        vehiculo=db.execute("""SELECT v.placa,v.tipo,v.usuario_id,u.activo AS usuario_activo
            FROM vehiculos v LEFT JOIN usuarios u ON u.id=v.usuario_id WHERE v.placa=?""",(placa,)).fetchone()
        if vehiculo is None:
            raise HTTPException(status_code=404,detail="Vehículo no registrado")
        if vehiculo["usuario_id"] is None or not vehiculo["usuario_activo"]:
            raise HTTPException(status_code=403,detail="El vehículo no tiene un cliente activo autorizado")
        mensualidad=db.execute("""SELECT id FROM mensualidades WHERE usuario_id=? AND estado='pagada'
            AND fecha_inicio<=? AND fecha_fin>=? ORDER BY fecha_fin DESC LIMIT 1""",
            (vehiculo["usuario_id"],hoy,hoy)).fetchone()
        if mensualidad is None:
            raise HTTPException(status_code=403,detail="El cliente no tiene una mensualidad pagada y vigente")
        celda=db.execute("SELECT codigo,tipo,activa FROM celdas WHERE codigo=?",(codigo,)).fetchone()
        if celda is None or not celda["activa"]:
            raise HTTPException(status_code=409,detail="La celda no existe o está inactiva")
        if celda["tipo"] not in {vehiculo["tipo"],"mixta"}:
            raise HTTPException(status_code=409,detail="La celda no es compatible con el tipo de vehículo")
        operador=db.execute("SELECT id FROM operadores WHERE id=? AND activo=1",(datos.operador_entrada_id,)).fetchone()
        if operador is None:
            raise HTTPException(status_code=422,detail="Selecciona un operador de entrada activo")
        ocupada=db.execute("SELECT 1 FROM estancias WHERE celda_codigo=? AND fecha_salida IS NULL",(codigo,)).fetchone()
        if ocupada:
            raise HTTPException(status_code=409,detail="La celda ya está ocupada")
        fecha=datetime.now().isoformat(timespec="seconds")
        try:
            cur=db.execute("""INSERT INTO estancias
                (vehiculo_placa,celda_codigo,operador_entrada_id,fecha_entrada)
                VALUES(?,?,?,?)""",(placa,codigo,datos.operador_entrada_id,fecha))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409,detail="El vehículo ya tiene una estancia abierta o la celda fue ocupada")
        return {"mensaje":"Entrada registrada","estancia_id":cur.lastrowid,"placa":placa,"celda":codigo,"fecha_entrada":fecha}


@app.get("/vehiculos/{placa}/estado")
def consultar_estado(placa: str):
    placa=placa_normalizada(placa)
    if not placa:
        raise HTTPException(status_code=422,detail="La placa es obligatoria")
    with conectar() as db:
        if not db.execute("SELECT 1 FROM vehiculos WHERE placa=?",(placa,)).fetchone():
            raise HTTPException(status_code=404,detail="Vehículo no registrado")
        estancia=db.execute("""SELECT e.celda_codigo,e.fecha_entrada,oe.nombre AS operador_entrada
            FROM estancias e JOIN operadores oe ON oe.id=e.operador_entrada_id
            WHERE e.vehiculo_placa=? AND e.fecha_salida IS NULL""",(placa,)).fetchone()
        if estancia is None:
            return {"placa":placa,"estado":"Fuera"}
        return {"placa":placa,"estado":"Dentro","celda":estancia["celda_codigo"],
                "operador_entrada":estancia["operador_entrada"],"fecha_entrada":estancia["fecha_entrada"]}


@app.post("/salidas/{placa}")
def registrar_salida(placa: str, datos: SalidaNueva):
    placa=placa_normalizada(placa)
    if not placa:
        raise HTTPException(status_code=422,detail="La placa es obligatoria")
    with conectar() as db:
        operador=db.execute("SELECT id FROM operadores WHERE id=? AND activo=1",(datos.operador_salida_id,)).fetchone()
        if operador is None:
            raise HTTPException(status_code=422,detail="Selecciona un operador de salida activo")
        estancia=db.execute("SELECT id FROM estancias WHERE vehiculo_placa=? AND fecha_salida IS NULL",(placa,)).fetchone()
        if estancia is None:
            raise HTTPException(status_code=404,detail="No hay una entrada abierta para ese vehículo")
        fecha=datetime.now().isoformat(timespec="seconds")
        db.execute("UPDATE estancias SET operador_salida_id=?,fecha_salida=? WHERE id=?",
                   (datos.operador_salida_id,fecha,estancia["id"]))
        return {"mensaje":"Salida registrada","placa":placa,"fecha_salida":fecha}
