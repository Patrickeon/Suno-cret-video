import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 워크스페이스 루트를 이 폴더로 고정 (상위 lockfile 오탐 방지)
  turbopack: {
    root: __dirname,
  },
  // 도커/Cloud Run 배포용 독립 실행 번들 (node server.js)
  output: "standalone",
};

export default nextConfig;
