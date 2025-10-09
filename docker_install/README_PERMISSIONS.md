# Docker Permission Issues - Solution Guide

## Problem
The entrypoint script was failing with permission errors:
1. Cannot create `/etc/ssl` - `update-ca-certificates` requires root privileges
2. Operation not permitted while changing ownership - `chown` requires root privileges

## Root Cause
The Dockerfile switches to a non-root user (`appuser` with UID 1000) before running the entrypoint script, but the entrypoint was trying to perform operations that require root privileges.

## Solution Applied

### 1. Entrypoint Script Changes
- Removed `update-ca-certificates` call (now done at build time in Dockerfile)
- Removed `chown` commands (unnecessary since we're already running as appuser)
- The script now only creates directories and runs Django commands

### 2. Dockerfile Changes
- Added `update-ca-certificates` at build time (runs as root)
- Created `/app/staticfiles` directory at build time with proper ownership
- Ensured all directories are owned by `appuser:appuser` before switching to non-root user

### 3. Host Directory Permissions
For the volume mounts to work properly, ensure the host directories have the correct permissions:

```bash
# On your host machine, set ownership to UID/GID 1000
sudo chown -R 1000:1000 ./logs
sudo chown -R 1000:1000 ./staticfiles

# Or make them world-writable (less secure but simpler)
chmod -R 777 ./logs
chmod -R 777 ./staticfiles
```

### 4. Custom CA Certificates (Optional)
If you need custom CA certificates:

1. Place your `.crt` files in the `./certs` directory on the host
2. Modify the Dockerfile to copy them before updating certificates:

```dockerfile
# Add this before the RUN update-ca-certificates line
COPY ./certs/*.crt /usr/local/share/ca-certificates/ 2>/dev/null || true
RUN update-ca-certificates
```

3. Rebuild the image

## Testing
After making these changes:

1. Rebuild your Docker image:
   ```bash
   docker-compose build
   ```

2. Start the services:
   ```bash
   docker-compose up -d
   ```

3. Check logs for any permission errors:
   ```bash
   docker-compose logs django-web
   ```
