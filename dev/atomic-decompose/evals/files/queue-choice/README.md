# Invoice service

FastAPI app on Python 3.12. Postgres 16 is the only datastore. Deployed as one AWS ECS service.

Background work we need:
- send about 2,000 invoice emails a day, retrying on SMTP failure;
- a nightly reconciliation job that runs about 20 minutes.

The team is two developers; nobody does operations full time.
