# Angel's Notes 
> These are my personal notes, here I'll write the tecnica desicions of why or how the project was developed, in order to create some sort of documentation for this project as well as a learning note for myself. 

* Remove the idea of creating 2 envs like "dev" and "prod" this was an old idea to show my skills as "devOps" but I want to get more focused in Data Quality and MLOps rather than "Hard Code Cloud DevOps"

**PR-001 — Repo hygiene baseline**
* Removed extra files in the "temp_files" that were test done previouly on this project.
* removed duplicated data in gitignore file
* added new virtual environment for python.
* Instead of using a setup.py or setup.cfg we are using now `pyproject.toml`
* added `makefile` in order to make things easier when deploying the architecture in a new pc or in local.
* Added `.pre-commit-cofing.yaml` file in order to check the quality of the code in terraform, python and jupyterNotebooks before sending it to the repo.
* Installed and enabled the command `gh` for "Git Hub CLI" so commands can be ran easly from the local terminal. 

**PR-002 - Inventory and protect prod buckets (no Terraform yet)** 
* The 2 json files in `/scripts/policies` are the bucket rules for protect the S3 buckets where the data is storage. 
* The `.txt` files in `/docs/inventory` are snapshots of current status in AWS about the data extracted with a readme file that explains why they exist. 
* Also, created a "safety belt" prior any refactor the file `scripts/00_inventory_and_protect.sh` 
    * Colors: allows the output termnal to show different colors based on "fail", "success" or any oter scenario when doing the dry run
    * Preconditions: verifies if the AWS profile, region and AWS command exists prior doing any change. 
    * Per-bucket work: creates and inventory of items in the buckets, enables the versioning on both buckets, adds the "deny policy" on both buckets.
    * Deny Delte Rule applies to all the users except for the __Admin__ in the AWS account. 
    * This was wrote in `.sh` file because these are pre-existing buckets, so __Terraform__ is not very good handling existing items, that's why the changes were done using __Bash__ and __AWS__.

**PR-003 - Move existing TF state to remote backend (no resource changes)**
On this PR the "refactor" is the pre-step move the terraform state file to a remote backend is done. 
* Created the `bootstrap/terrraform` directories in order to create the .tf files 
* dyamodb.tf, main.tf, and so on were created in order to set a S3 bucket in AWS and DynamoDB for blocking stated (as a real life production project)
* The local (as per now) is not scalable and just "toy project" like. HashiCorp's Cloud could be used but still we depend on "someone else's" service, so is a better idea to centralize everything in AWS with all the protection rules for that bucket and blcoking the state file with dynamoDB with a ver low cost. 