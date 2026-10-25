from datetime import datetime
import sqlite3

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from pathlib import Path
from fastapi.responses import FileResponse

app = FastAPI(title="Autos Colombia")
BASE_DATOS = "autos_colombia.db"


def conectar():
    conexion = sqlite3.connect(BASE_DATOS)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def crear_tablas():
    conexion = conectar()
    try:
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS vehiculos (
                placa TEXT PRIMARY KEY
            )
        """)
        conexion.execute("""
            CREATE TABLE IF NOT EXISTS estancias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                placa TEXT NOT NULL,
                celda TEXT NOT NULL,
                operador_entrada TEXT NOT NULL,
                operador_salida TEXT,
                fecha_entrada TEXT NOT NULL,
                fecha_salida TEXT,
                FOREIGN KEY (placa) REFERENCES vehiculos(placa)
            )
        """)
        conexion.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS una_estancia_abierta_por_vehiculo
            ON estancias(placa) WHERE fecha_salida IS NULL
        """)
        conexion.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS una_estancia_abierta_por_celda
            ON estancias(celda) WHERE fecha_salida IS NULL
        """)
        conexion.commit()
    finally:
        conexion.close()


crear_tablas()


class VehiculoNuevo(BaseModel):
    placa: str


class EntradaNueva(BaseModel):
    placa: str
    celda: str
    operador: str


class SalidaNueva(BaseModel):
    operador: str


def normalizar_placa(placa: str) -> str:
    return "".join(placa.upper().split())


@app.get("/")
def inicio():
    return FileResponse(Path(__file__).with_name("index.html"))


@app.post("/vehiculos")
def registrar_vehiculo(datos: VehiculoNuevo):
    placa = normalizar_placa(datos.placa)
    conexion = conectar()
    try:
        conexion.execute(
            "INSERT INTO vehiculos (placa) VALUES (?)",
            (placa,)
        )
        conexion.commit()
        return {"mensaje": "Vehículo registrado", "placa": placa}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ese vehículo ya está registrado")
    finally:
        conexion.close()


@app.get("/vehiculos")
def listar_vehiculos():
    conexion = conectar()
    try:
        filas = conexion.execute(
            "SELECT placa FROM vehiculos ORDER BY placa"
        ).fetchall()
        return [dict(fila) for fila in filas]
    finally:
        conexion.close()


@app.post("/entradas")
def registrar_entrada(datos: EntradaNueva):
    placa = normalizar_placa(datos.placa)
    celda = datos.celda.strip().upper()
    operador = datos.operador.strip()

    conexion = conectar()
    try:
        vehiculo = conexion.execute(
            "SELECT placa FROM vehiculos WHERE placa = ?", (placa,)
        ).fetchone()

        if vehiculo is None:
            raise HTTPException(status_code=404, detail="Vehículo no registrado")

        fecha = datetime.now().isoformat(timespec="seconds")
        conexion.execute(
            """INSERT INTO estancias
               (placa, celda, operador_entrada, fecha_entrada)
               VALUES (?, ?, ?, ?)""",
            (placa, celda, operador, fecha)
        )
        conexion.commit()
        return {
            "mensaje": "Entrada registrada",
            "placa": placa,
            "celda": celda,
            "fecha_entrada": fecha
        }
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="El vehículo ya está dentro o la celda está ocupada"
        )
    finally:
        conexion.close()


@app.get("/vehiculos/{placa}/estado")
def consultar_estado(placa: str):
    placa = normalizar_placa(placa)
    conexion = conectar()
    try:
        vehiculo = conexion.execute(
            "SELECT placa FROM vehiculos WHERE placa = ?", (placa,)
        ).fetchone()

        if vehiculo is None:
            raise HTTPException(status_code=404, detail="Vehículo no registrado")

        estancia = conexion.execute(
            """SELECT celda, operador_entrada, fecha_entrada
               FROM estancias
               WHERE placa = ? AND fecha_salida IS NULL""",
            (placa,)
        ).fetchone()

        if estancia is None:
            return {"placa": placa, "estado": "Fuera"}

        return {
            "placa": placa,
            "estado": "Dentro",
            "celda": estancia["celda"],
            "operador_entrada": estancia["operador_entrada"],
            "fecha_entrada": estancia["fecha_entrada"]
        }
    finally:
        conexion.close()


@app.post("/salidas/{placa}")
def registrar_salida(placa: str, datos: SalidaNueva):
    placa = normalizar_placa(placa)
    conexion = conectar()
    try:
        estancia = conexion.execute(
            """SELECT id FROM estancias
               WHERE placa = ? AND fecha_salida IS NULL""",
            (placa,)
        ).fetchone()

        if estancia is None:
            raise HTTPException(
                status_code=404,
                detail="No hay una entrada abierta para ese vehículo"
            )

        fecha = datetime.now().isoformat(timespec="seconds")
        conexion.execute(
            """UPDATE estancias
               SET operador_salida = ?, fecha_salida = ?
               WHERE id = ?""",
            (datos.operador.strip(), fecha, estancia["id"])
        )
        conexion.commit()
        return {
            "mensaje": "Salida registrada",
            "placa": placa,
            "fecha_salida": fecha
        }
    finally:
        conexion.close()