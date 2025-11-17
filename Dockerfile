# Stage 1: Base build stage
FROM python:3.13-slim-bookworm AS builder
 
# Create the app directory
RUN mkdir /app
 
# Set the working directory
WORKDIR /app
 
# Set environment variables to optimize Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1 
 
# Install dependencies first for caching benefit
RUN pip install --upgrade pip 
COPY requirements.txt /app/ 
RUN pip install --no-cache-dir -r requirements.txt
 
# Stage 2: Production stage
FROM python:3.13-slim-bookworm
 
# Create user and required directories
RUN groupadd -g 1000 appuser && \
    useradd -m -u 1000 -g appuser appuser && \
    mkdir /app && \
    mkdir -p /app/static && \
    mkdir -p /app/staticfiles && \
    mkdir -p /app/logs && \
    chown -R appuser:appuser /app

# Copy the Python dependencies from the builder stage
COPY --from=builder /usr/local/lib/python3.13/site-packages/ /usr/local/lib/python3.13/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgl1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Update CA certificates at build time (if custom certs are needed, add them before this step)
# This runs as root before switching to appuser
RUN update-ca-certificates

# Set the working directory
WORKDIR /app
 
# Copy remaining application code
COPY --chown=appuser:appuser . .

# Set environment variables to optimize Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1 

# Copy entrypoint and make it executable (before switching user)
COPY --chown=appuser:appuser entrypoint.docker.sh /app/entrypoint.docker.sh
RUN chmod +x /app/entrypoint.docker.sh

# Switch to non-root user
USER appuser

# Expose the application port
EXPOSE 8000 
 
# Start the application using the entrypoint script
CMD ["/app/entrypoint.docker.sh"]