# create_requirements.py

import subprocess

# Список зависимостей для проекта
dependencies = [
    "fastapi",
    "uvicorn",
    "yandex-music",
    "python-dotenv"
]

# Создание requirements.txt
with open("requirements.txt", "w") as f:
    for dep in dependencies:
        f.write(f"{dep}\n")

print("Файл requirements.txt успешно создан.")
