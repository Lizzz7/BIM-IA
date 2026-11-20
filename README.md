# IBM-IA · NEXO OBRA

Panel para preparar, controlar y reportar valorizaciones de obra a partir de modelos de Revit.

## Contenido

- `1_Panel/`: panel HTML/JavaScript y scripts de generación.
- `2_Complemento_Revit/`: complemento C#/.NET para Revit y herramientas Dynamo.
- `3_Modelo_y_parametros/`: modelo de prueba, parámetros y datos exportados.
- `4_Python/`: cálculo, metrados y cronograma.
- `5_Documentacion/`: guías, presupuestos y documentación.

Consulta [LEEME_REUTILIZACION.md](LEEME_REUTILIZACION.md) para conocer la estructura y el contexto del proyecto.

## Trabajo en equipo

Clona el repositorio, crea una rama para cada cambio y abre un pull request hacia `main`.
No publiques credenciales ni archivos `.env`. Los archivos de compilación y los respaldos locales no se versionan.

El panel está en `1_Panel/index.html`. La integración con Revit requiere el complemento y el entorno correspondiente; consulta los proyectos en `2_Complemento_Revit/`.
