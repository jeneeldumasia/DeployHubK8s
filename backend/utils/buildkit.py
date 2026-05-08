import subprocess
import uuid
import os
import json
import base64
import tempfile
import shutil
from typing import Dict, Optional

import boto3
from config import settings


def build_image(context_path: str, dockerfile_path: str, image_name: Optional[str] = None) -> Dict[str, str]:
    if not image_name:
        image_name = f"build-{uuid.uuid4().hex}"

    dockerfile_dir = os.path.dirname(dockerfile_path)
    if not dockerfile_dir:
        dockerfile_dir = context_path

    dockerfile_name = os.path.basename(dockerfile_path)

    # Only use insecure flag for local registries (e.g. registry:5000).
    # Cloud registries (ECR, DockerHub) always use HTTPS – never add insecure flag.
    output_opts = f"type=image,name={image_name},push=true"
    if settings.registry_insecure:
        output_opts += ",registry.insecure=true"

    cmd = [
        "buildctl", "build",
        "--frontend", "dockerfile.v0",
        "--local", f"context={context_path}",
        "--local", f"dockerfile={dockerfile_dir}",
        "--opt", f"filename={dockerfile_name}",
        "--output", output_opts,
    ]

    env = os.environ.copy()
    # Use BUILDKIT_HOST if set (points to in-cluster buildkitd service)
    buildkit_host = env.get("BUILDKIT_HOST", settings.buildkit_addr)
    env["BUILDKIT_HOST"] = buildkit_host

    # Handle ECR Authentication if needed
    docker_config_dir = None
    if ".dkr.ecr." in image_name:
        try:
            # Determine region from image name or settings
            # Format: account.dkr.ecr.region.amazonaws.com/repo
            region = settings.aws_region
            if ".dkr.ecr." in image_name:
                parts = image_name.split(".")
                if len(parts) > 3:
                    region = parts[3]
            
            ecr = boto3.client("ecr", region_name=region)
            auth_data = ecr.get_authorization_token()["authorizationData"][0]
            token = base64.b64decode(auth_data["authorizationToken"]).decode("utf-8")
            username, password = token.split(":")
            registry_url = auth_data["proxyEndpoint"]

            # Create temporary Docker config
            docker_config_dir = tempfile.mkdtemp()
            config = {
                "auths": {
                    registry_url: {
                        "auth": base64.b64encode(f"{username}:{password}".encode()).decode()
                    }
                }
            }
            with open(os.path.join(docker_config_dir, "config.json"), "w") as f:
                json.dump(config, f)
            
            env["DOCKER_CONFIG"] = docker_config_dir
        except Exception as e:
            return {
                "status": "error",
                "image": image_name,
                "logs": f"ECR authentication failed: {str(e)}",
            }

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
            env=env,
        )
        return {
            "status": "success",
            "image": image_name,
            "logs": result.stdout,
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "image": image_name,
            "logs": e.stdout,
        }
    except Exception as e:
        return {
            "status": "error",
            "image": image_name,
            "logs": str(e),
        }
    finally:
        if docker_config_dir and os.path.exists(docker_config_dir):
            shutil.rmtree(docker_config_dir)
