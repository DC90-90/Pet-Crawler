# Prepared-artifact consumer, NOT a workspace manifest copier or implicit build.
# First run scripts/verify_clean_release.py against the exact saved source SHA.
FROM python:3.11-slim AS verified
WORKDIR /source
COPY . .
RUN python scripts/verify_release_artifact.py --require-committed

FROM nginx:1.25-alpine
COPY --from=verified /source/frontend/build /usr/share/nginx/html
COPY --from=verified /source/deploy/nginx-frontend.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]