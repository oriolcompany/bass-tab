# Bass Tab

App local que separa un MP3 en voces, batería, bajo y resto, convierte el bajo en tablatura de 4 cuerdas y la mueve con el audio.

La canción queda guardada. Volver a abrir el mismo archivo no repite la separación: se elige desde el menú. La afinación es la estándar, G D A E.

## Arranque

Doble clic en `Bass Tab.exe`. Abre http://127.0.0.1:8790.

En esta máquina usa el entorno de karaoke-party, que ya trae el separador. En un ordenador nuevo, el ejecutable instala Python 3.12 y ffmpeg si faltan, y después PyTorch. La primera vez hace falta internet y, con NVIDIA, descarga unos 3 GB.

También vale `Bass Tab.bat`, que llama al mismo arranque.

Para desarrollarlo a mano:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[stems]"
python -m bass_tab
```

Sin tarjeta NVIDIA: `pip install -e ".[stems-cpu]"`.

## Otro ordenador

Copia la carpeta entera, o clona el repositorio, y abre `Bass Tab.exe`. No copies `.venv`, `.git` ni `tools`. El `.exe` no lleva el modelo de separación dentro: PyTorch y CUDA se rompen si se congelan en un solo archivo. El ejecutable prepara un entorno de Python y arranca el programa.

## Uso

1. En el menú, suelta el MP3 completo o pulsa Añadir canción.
2. La primera vez separa las pistas y escribe la tablatura. La canción queda en la lista.
3. La siguiente vez, el mismo archivo se abre al momento. Tocar entra en la tablatura.
4. Quitar la saca de la lista. Si la vuelves a añadir, se separa de nuevo.
5. La tablatura se desplaza con el cursor. Clic en un traste o en la barra para saltar.
6. Espacio reproduce o pausa. Las flechas saltan 2 segundos.
7. 50 % y 75 % bajan la velocidad sin cambiar el tono. Baja el volumen del bajo, o ponle Mute, para oírte a ti.
8. Canciones vuelve al menú. Repetir vuelve al principio al llegar al final.

## Variables

| Variable | Efecto |
| --- | --- |
| `BASS_TAB_SONGS` | Carpeta de canciones guardadas. Por defecto `%LOCALAPPDATA%\BassTab\songs`. |
| `BASS_TAB_MODELS` | Carpeta de pesos de Demucs. Si no existe, reutiliza los de Karaoke Party o Stem Mixer. |
