# 프론트엔드: Next.js standalone — Cloud Run 용
# 빌드 컨텍스트는 frontend/ :
#   docker build -f frontend/Dockerfile \
#     --build-arg NEXT_PUBLIC_API_BASE=https://<백엔드-URL> -t suno-frontend frontend
FROM node:22-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# 클라이언트 번들에 백엔드 주소가 빌드타임에 박힘 (배포된 백엔드 URL 지정)
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
RUN npm run build

FROM node:22-slim AS run
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8080
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 8080
CMD ["node", "server.js"]
