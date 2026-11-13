# UY-044 — el oro de Uruguay en la nube

Cómo se construye, cómo se comprueba, cómo se vuelve atrás y el único paso que hace el owner a
mano: la excepción de la Deny de borrado del bucket.

## Qué corre cada noche

`lottery-uy-pipeline-prod`: `Fetch → Silver → ValidateSilver → BuildGold`. En un dry run la
máquina termina después de `ValidateSilver` (el oro escribe; un dry run, no).

`BuildGold` invoca la Lambda `lottery-uy-gold-prod` (`sorteos.core.gold`):

1. **Construye** las seis tablas de `sql/uy/gold/` como CTAS de Athena (`lottery-uy-wg`) en
   tablas `stg_gold_*`, cada una en `uy/gold/<tabla>/run=<generación>/`. La generación es la
   hora UTC de la corrida (`20261111T023005Z`).
2. **Cuenta** las filas de las seis. Si alguna quedó vacía, no publica ninguna.
3. **Hace el swap** de las seis: cada tabla publicada pasa a apuntar a su carpeta nueva con un
   `UpdateTable`. Hasta ese momento, quien consulta ve el oro de la noche anterior, entero.
4. **Retira** las generaciones viejas: deja la viva y la anterior publicada.

Si algo falla, la ejecución termina en `FAILED`, la alarma `lottery-uy-pipeline-prod-failed`
manda el correo y el oro publicado sigue siendo el de la noche anterior.

## El paso del owner: la excepción de la Deny (una sola vez)

La política del bucket `lottery-partitioned-storage-prod` (PR-002, fuera de Terraform) niega
todo borrado salvo a root y al rol de oro de Santa Lucía. El rol de oro de UY necesita borrar
**solo** bajo `uy/gold/`.

**Sin este paso el oro se construye y se publica igual**, pero la tercera noche el paso de
retiro falla (`S3 refused to delete ... AccessDenied`) y la ejecución sale en `FAILED` cada
noche hasta aplicarlo. Las dos primeras corridas no borran nada.

La política nueva agrega el rol a la excepción del statement que ya existe y suma un segundo
statement que le niega a ese rol borrar fuera de `uy/gold/`:

```bash
cat > /tmp/uy-gold-bucket-policy.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Phase0DenyDeleteExceptRoot",
      "Effect": "Deny",
      "Principal": "*",
      "Action": ["s3:DeleteBucket", "s3:DeleteObject*"],
      "Resource": [
        "arn:aws:s3:::lottery-partitioned-storage-prod",
        "arn:aws:s3:::lottery-partitioned-storage-prod/*"
      ],
      "Condition": {
        "StringNotEquals": {
          "aws:PrincipalArn": [
            "arn:aws:iam::913524903233:root",
            "arn:aws:iam::913524903233:role/lottery-gold-purge-role-prod",
            "arn:aws:iam::913524903233:role/lottery-uy-gold-lambda-prod"
          ]
        }
      }
    },
    {
      "Sid": "UyGoldDeletesOnlyUnderUyGold",
      "Effect": "Deny",
      "Principal": "*",
      "Action": ["s3:DeleteBucket", "s3:DeleteObject*"],
      "NotResource": "arn:aws:s3:::lottery-partitioned-storage-prod/uy/gold/*",
      "Condition": {
        "StringEquals": {
          "aws:PrincipalArn": "arn:aws:iam::913524903233:role/lottery-uy-gold-lambda-prod"
        }
      }
    }
  ]
}
JSON

# Antes: guardar la política actual (es el rollback de este paso).
aws s3api get-bucket-policy --bucket lottery-partitioned-storage-prod \
  --query Policy --output text > /tmp/bucket-policy-antes.json

aws s3api put-bucket-policy --bucket lottery-partitioned-storage-prod \
  --policy file:///tmp/uy-gold-bucket-policy.json

# Después: debe mostrar los dos statements.
aws s3api get-bucket-policy --bucket lottery-partitioned-storage-prod \
  --query Policy --output text | python -m json.tool
```

El primer statement es el de hoy con una línea más. El rol de oro de Santa Lucía no cambia.
El IAM del rol de UY ya limita por su cuenta `s3:DeleteObject*` a `uy/gold/*` (`gold.tf`); el
segundo statement es la misma regla del lado del bucket.

## Comprobar una corrida

```bash
# La salida de la última ejecución: $.gold.report trae la generación, las filas por tabla y
# lo que se retiró.
aws stepfunctions list-executions --max-results 1 --query 'executions[0].[name,status]' \
  --state-machine-arn arn:aws:states:us-east-1:913524903233:stateMachine:lottery-uy-pipeline-prod

# Las seis tablas, la generación que apuntan y la anterior.
aws glue get-tables --database-name lottery_uy_db --expression '^gold_' \
  --query 'TableList[].[Name,Parameters."gold.generation",Parameters."gold.previous_generations"]' \
  --output table

# Lo que hay en S3 por tabla: la viva y, a partir de la segunda noche, la anterior.
aws s3 ls s3://lottery-partitioned-storage-prod/uy/gold/gold_quiniela_repeats/
```

Las seis tablas deben apuntar a **la misma** generación. `make uy-gold-build` corre la Lambda a
mano, fuera de la máquina (es una construcción real: no hay dry run del oro).

## Quién puede consultar el oro

Las tablas de oro las crea el rol de la Lambda, y en esta cuenta Lake Formation le da una tabla
nueva solo a quien la crea. Ser administrador del data lake permite otorgar permisos, no leer.
Por eso `gold.tf` otorga `SELECT` y `DESCRIBE` sobre todas las tablas de `lottery_uy_db` (con
comodín, porque las de oro no las nombra Terraform) a:

- el usuario IAM que aplica el stack (hoy, `angel-adming`), y
- cada ARN de `var.catalog_reader_arns`.

Si Athena responde `Relation contains no accessible columns`, a quien consulta le falta ese
grant: se suma su ARN a `catalog_reader_arns` y se aplica.

## Volver a la generación anterior

Cada tabla recuerda la anterior en `gold.previous_generations`, y sus archivos siguen en S3.
Volver es apuntar la tabla a esa carpeta; con el rol de administrador, en el editor de Athena
(workgroup `lottery-uy-wg`):

```sql
ALTER TABLE lottery_uy_db.gold_quiniela_repeats
SET LOCATION 's3://lottery-partitioned-storage-prod/uy/gold/gold_quiniela_repeats/run=<generación anterior>/';
```

Hay que hacerlo en las seis tablas para que queden en la misma noche. La corrida siguiente
construye una generación nueva y vuelve a publicar: el rollback dura hasta entonces. Si lo que
está mal es el SQL, se arregla el SQL.

## Si falla

| Mensaje en la ejecución | Qué pasó | Qué queda publicado |
|---|---|---|
| `Athena failed: {...}` | Un CTAS falló (SQL, permisos, límite de 100 MB del workgroup) | El oro anterior, entero |
| `built with no rows` | Una tabla salió vacía | El oro anterior, entero |
| `swap stopped at <tabla>` | Un `UpdateTable` falló a mitad | Las tablas nombradas en el mensaje, en la generación nueva; el resto en la anterior. La corrida siguiente las alinea |
| `S3 refused to delete` | Falta la excepción de la Deny (arriba) | El oro **nuevo**, bien publicado; solo falló la limpieza |
| `Athena did not finish in 150 s` | Athena no respondió; las consultas se cancelaron | El oro anterior, entero |
