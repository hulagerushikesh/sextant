# The React UI, built once and served as static assets.
FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# Vite inlines env vars at build time, so the API URL has to be known here --
# setting it at runtime would have no effect at all.
ARG VITE_SERVER_URL=http://localhost:8000
ENV VITE_SERVER_URL=$VITE_SERVER_URL
RUN npm run build

FROM node:22-alpine
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./

EXPOSE 3000
# vite preview, not a hardened static server. Good enough to try the project;
# put nginx or a CDN in front of `dist/` for anything real.
CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "3000"]
