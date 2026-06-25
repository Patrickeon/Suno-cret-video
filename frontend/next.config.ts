import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 워크스페이스 루트를 이 폴더로 고정 (상위 lockfile 오탐 방지)
  turbopack: {
    root: __dirname,
  },
};

export default nextConfig;
