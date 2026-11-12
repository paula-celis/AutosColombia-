# Autos Colombia

Sistema web local para gestionar vehículos, entradas/salidas, clientes, celdas, operadores y mensualidades.

## Requisitos

- Python 3.10 o posterior
- Dependencias de `requirements.txt`

## Ejecución

Desde esta carpeta:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Abre `http://127.0.0.1:8000`. La documentación interactiva de la API queda en `http://127.0.0.1:8000/docs`. SQLite se guarda en `autos_colombia.db` junto a `main.py`.

## Flujo para registrar una entrada

1. Crear usuario en **Usuarios**.
2. Registrar una mensualidad vigente con estado **Pagada** en **Mensualidades**.
3. Registrar vehículo asociado al cliente y seleccionar tipo.
4. Registrar celda compatible (carro, moto o mixta) y operador activo.
5. En **Registrar entrada**, seleccionar un vehículo sin estancia abierta, una celda disponible y compatible, y un operador activo.
6. Para cerrar, seleccionar un operador de salida activo en el diálogo de salida.

El prototipo migra las antiguas celdas y operadores textuales a tablas relacionadas y conserva la tabla histórica `estancias_legacy`. Los vehículos antiguos sin usuario se completan desde **Asociar vehículo existente**.

## Modelo y mockups

- `MER_EA2_corregido.md`: MER, MR, físico, multiplicidades corregidas, clases, casos de uso, paquetes y plan resumido de pruebas.
- `MER 2.mdj`, `Diagrama de clases.mdj`, `diagrama {casos de uso.mdj` y `Diagtrama de paquetes.mdj`: diagramas editables de StarUML con relaciones y dependencias.
- `Autos_Colombia_Mockups_EA2_corregidos.svg`: pantallas conceptuales con estados de error para campos obligatorios, celdas, mensualidad y salida. Se puede abrir en el navegador o importar en Figma como SVG.

Las pruebas de aceptación están especificadas en el documento de modelo. Antes de la entrega, ejecútalas en la instancia local, conserva evidencia y anéxala al informe.
