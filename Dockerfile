# Use a lightweight but compatible base image
FROM python:3.11-slim-bullseye

# Install system dependencies needed for dlib and opencv
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    pkg-config \
    libx11-dev \
    libatlas-base-dev \
    libgtk-3-dev \
    libboost-python-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
# We force single-thread compilation to avoid Render "Out of Memory" errors
COPY requirements.txt .
RUN MAKEFLAGS="-j1" pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the port Gunicorn will run on
EXPOSE 10000

# Command to run the application
# Using miniproject.app:app because the folder structure has the app inside 'miniproject'
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "miniproject.app:app"]
