#!/usr/bin/bash
# scripts/build-and-push.sh
# Usage: ./scripts/build-and-push.sh <registry_prefix> <tag> <username>
# Example: ./scripts/build-and-push.sh your.registry.example.com/shopnow v1.0 aryan

set -euo pipefail

# Check if all required parameters are provided
if [ $# -ne 3 ]; then
    echo "Error: All parameters are required!"
    echo "Usage: $0 <registry_prefix> <tag> <username>"
    echo "Example: $0 123456789012.dkr.ecr.us-east-1.amazonaws.com/shopnow v1.0 aryan"
    echo ""
    echo "Parameters:"
    echo "  registry_prefix: Your container registry URL (e.g., ECR, Docker Hub)"
    echo "  tag: Version tag for the images (e.g., v1.0, latest, dev)"
    echo "  username: Username for the learner (e.g., aryan, john, sarah)"
    exit 1
fi

REGISTRY=$1
TAG=$2
USER_NAME=$3
DOCKER_OPTS=${DOCKER_OPTS:-}

echo "Building images for user: $USER_NAME"
echo "Registry: $REGISTRY"
echo "Tag: $TAG"
echo ""

build_and_push() {
  local dir=$1
  local name=$2
  local build_args=$3
  echo "-> Building ${name} from ${dir}"
  docker build ${DOCKER_OPTS} ${build_args} -t "${REGISTRY}/${name}:${TAG}" "${dir}"
  echo "-> Pushing ${REGISTRY}/${name}:${TAG}"
  docker push "${REGISTRY}/${name}:${TAG}"
  echo
}

# Validate docker available
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found in PATH"
  exit 2
fi

# Build components
build_and_push "./frontend" "frontend" "--build-arg USER_NAME=${USER_NAME}"
build_and_push "./backend/helloService" "helloservice" ""
build_and_push "./backend/profileService" "profileservice" ""


echo "All images built and pushed:"
echo "  ${REGISTRY}/frontend:${TAG} (for user: ${USER_NAME})"
echo "  ${REGISTRY}/helloservice:${TAG}"
echo "  ${REGISTRY}/profileservice:${TAG} (for user: ${USER_NAME})"

