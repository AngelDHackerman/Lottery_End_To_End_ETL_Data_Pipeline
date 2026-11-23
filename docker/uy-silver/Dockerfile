# The UY silver Lambda image (UY-042.4.1; DESIGN.md D29). Built and pushed by
# `make uy-silver-push`. The build context is NOT the repo: it is build/uy-silver-context,
# which scripts/build_uy_silver_context.sh fills with exactly the files copied below.
#
# The base is AWS's Lambda image for python3.12, pinned by the digest of its linux/amd64
# manifest (2026-11-04): a tag would move under us every week. To take AWS's patches, look
# the new digest up (`docker buildx imagetools inspect public.ecr.aws/lambda/python:3.12`)
# and change it here; the image tag (scripts/uy_silver_tag.py hashes this file) moves with it.
FROM public.ecr.aws/lambda/python:3.12@sha256:012bacf013888cce3ba3d6f45348f1ce05c94b83c6b9c0e5167eaa4b93fcdfe8

# Exactly the lock: every wheel checked against its hash, nothing resolved or compiled here.
# boto3 comes with the base image.
COPY requirements/uy-silver.lock /tmp/uy-silver.lock
RUN pip install --no-cache-dir --disable-pip-version-check --require-hashes --no-deps \
      --only-binary=:all: --target "${LAMBDA_TASK_ROOT}" -r /tmp/uy-silver.lock \
 && rm -rf "${LAMBDA_TASK_ROOT}/bin" /tmp/uy-silver.lock

# The code: the sorteos package and the three stdlib-only files of loteria its entry points
# import for structured logging (loteria.common.logging_setup).
COPY src/sorteos ${LAMBDA_TASK_ROOT}/sorteos
COPY src/loteria/__init__.py ${LAMBDA_TASK_ROOT}/loteria/__init__.py
COPY src/loteria/common/__init__.py src/loteria/common/logging_setup.py ${LAMBDA_TASK_ROOT}/loteria/common/

CMD ["sorteos.uy.lambda_silver.handler"]
