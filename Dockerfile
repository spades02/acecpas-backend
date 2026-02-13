# Use full Python image to avoid missing build tools
FROM python:3.11

# Set the working directory in the container
WORKDIR /code

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install pip dependencies
COPY requirements.txt /code/

# 1. Upgrade pip
# 2. Install requirements with:
#    --prefer-binary: Don't compile if a wheel exists (Huge speedup)
#    --default-timeout=1000: Don't fail on slow connections
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --upgrade --default-timeout=1000 --prefer-binary -r /code/requirements.txt

# Copy the rest of the code
COPY . /code/

# Expose the port
EXPOSE 8000

# Command to run (using uvicorn)
# Command to run (using uvicorn)
# Use shell form to allow variable expansion for PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
