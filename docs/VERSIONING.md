# Docker Image Versioning Guide

## Overview
The GitHub Actions workflow now supports multiple tagging strategies for Docker images.

## Tagging Strategy

### 1. **Commit SHA Tags** (Always created)
Every push creates a tag with the git commit SHA:
```
public.ecr.aws/g0w3c0z2/draw-client-2.0:<commit-sha>
```
Example: `public.ecr.aws/g0w3c0z2/draw-client-2.0:a1b2c3d4`

### 2. **Branch Tags**
- **main branch** → `latest` tag
- **develop branch** → `develop` tag
- **other branches** → `<branch-name>` tag

### 3. **Version Tags** (Semantic Versioning)
When you push a git tag following the pattern `v*.*.*`, it creates:
- Version-specific tag: `v1.0.0`, `v2.1.3`, etc.
- **AND** updates the `latest` tag (for releases only)

## How to Create a Versioned Release

### Step 1: Create and Push a Git Tag
```bash
# Create a version tag (e.g., v1.0.0)
git tag -a v1.0.0 -m "Release version 1.0.0"

# Push the tag to GitHub
git push origin v1.0.0
```

### Step 2: GitHub Actions Automatically Creates
The workflow will automatically build and push:
1. `public.ecr.aws/g0w3c0z2/draw-client-2.0:<commit-sha>`
2. `public.ecr.aws/g0w3c0z2/draw-client-2.0:v1.0.0`
3. `public.ecr.aws/g0w3c0z2/draw-client-2.0:latest` (updated to v1.0.0)

## Examples

### Example 1: Regular Development Push to `main`
```bash
git push origin main
```
**Creates:**
- `draw-client-2.0:a1b2c3d4` (commit SHA)
- `draw-client-2.0:latest` (branch tag)

### Example 2: Push to `develop` Branch
```bash
git push origin develop
```
**Creates:**
- `draw-client-2.0:b2c3d4e5` (commit SHA)
- `draw-client-2.0:develop` (branch tag)

### Example 3: Release Version 1.0.0
```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```
**Creates:**
- `draw-client-2.0:c3d4e5f6` (commit SHA)
- `draw-client-2.0:v1.0.0` (version tag)
- `draw-client-2.0:latest` (updated to point to v1.0.0)

### Example 4: Patch Release 1.0.1
```bash
git tag -a v1.0.1 -m "Bugfix release v1.0.1"
git push origin v1.0.1
```
**Creates:**
- `draw-client-2.0:d4e5f6g7` (commit SHA)
- `draw-client-2.0:v1.0.1` (version tag)
- `draw-client-2.0:latest` (updated to point to v1.0.1)

## Pulling Specific Versions

### Pull Latest Release
```bash
docker pull public.ecr.aws/g0w3c0z2/draw-client-2.0:latest
```

### Pull Specific Version
```bash
docker pull public.ecr.aws/g0w3c0z2/draw-client-2.0:v1.0.0
```

### Pull Development Version
```bash
docker pull public.ecr.aws/g0w3c0z2/draw-client-2.0:develop
```

### Pull Specific Commit
```bash
docker pull public.ecr.aws/g0w3c0z2/draw-client-2.0:a1b2c3d4
```

## Semantic Versioning Guidelines

Follow [Semantic Versioning 2.0.0](https://semver.org/):

- **MAJOR version** (v2.0.0): Incompatible API changes
- **MINOR version** (v1.1.0): New functionality, backwards compatible
- **PATCH version** (v1.0.1): Backwards compatible bug fixes

### Examples:
- `v1.0.0` - Initial release
- `v1.0.1` - Bug fix
- `v1.1.0` - New feature added
- `v2.0.0` - Breaking changes

## Deleting Tags

### Delete Local Tag
```bash
git tag -d v1.0.0
```

### Delete Remote Tag
```bash
git push origin --delete v1.0.0
```

**Note:** Deleting a git tag does NOT delete the Docker image from ECR.

## Best Practices

1. **Always test before tagging** - Test thoroughly on `develop` branch first
2. **Use meaningful version numbers** - Follow semantic versioning
3. **Add release notes** - Use annotated tags with `-a` and `-m` flags
4. **Don't reuse version numbers** - Once released, don't change it
5. **Keep CHANGELOG.md updated** - Document changes for each version

## Workflow Triggers

The workflow runs on:
- ✅ Push to `main` branch
- ✅ Push to `develop` branch
- ✅ Push of tags matching `v*.*.*` pattern

## Troubleshooting

### Tag not triggering workflow?
- Ensure tag matches pattern: `v1.0.0` ✅, `1.0.0` ❌
- Check GitHub Actions tab for workflow runs
- Verify AWS credentials are configured

### Image not appearing in ECR?
- Check workflow logs in GitHub Actions
- Verify ECR repository exists
- Confirm AWS permissions are correct
