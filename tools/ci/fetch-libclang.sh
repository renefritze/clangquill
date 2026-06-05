#!/usr/bin/env bash
# Fetch a self-contained libclang from the official LLVM release and unpack the
# pieces clangquill needs into a prefix usable as CMake's LibClang_ROOT.
#
# Why the official "LLVM-<ver>-Linux-<arch>" package: from LLVM 19/20 onward it
# ships a libclang.so with libLLVM *statically linked in* (NEEDED is only
# libc/libm/libz/ld-linux — no shared libLLVM.so). So `auditwheel repair`
# vendors a single self-contained .so rather than the ~129 MB monolithic
# libLLVM the distro libclang drags in (see docs ADR-0001). The trade-off is a
# GLIBC_2.34 floor, so the wheels must be built in a manylinux_2_34 image.
#
# Usage:  fetch-libclang.sh [PREFIX]      (PREFIX defaults to /opt/libclang)
# Env:    LLVM_VERSION                     (defaults to the pinned version below)
set -euo pipefail

ver="${LLVM_VERSION:-20.1.8}"
prefix="${1:-/opt/libclang}"

if [ "$(uname -s)" != "Linux" ]; then
  echo "fetch-libclang: this script only supports Linux" >&2
  exit 1
fi

case "$(uname -m)" in
  x86_64 | amd64) arch="X64" ;;
  aarch64 | arm64) arch="ARM64" ;;
  *)
    echo "fetch-libclang: unsupported architecture $(uname -m)" >&2
    exit 1
    ;;
esac

tarball="LLVM-${ver}-Linux-${arch}.tar.xz"
url="https://github.com/llvm/llvm-project/releases/download/llvmorg-${ver}/${tarball}"

mkdir -p "$prefix"
echo "fetch-libclang: downloading ${url}" >&2
# Extract only the shared library, the C API headers, and the license; the rest
# of the release (clang/lld/etc.) is multiple GB unpacked and unused here.
curl -fsSL --retry 3 --retry-delay 2 "$url" \
  | tar -xJ -C "$prefix" --strip-components=1 --wildcards --no-anchored \
        '*/lib/libclang.so*' '*/include/clang-c/*' '*/LICENSE.TXT'

# FindLibClang looks for a bare `libclang.so`; the release ships the versioned
# names plus that symlink, but recreate it defensively if it is missing.
if [ ! -e "${prefix}/lib/libclang.so" ]; then
  real="$(find "${prefix}/lib" -maxdepth 1 -name 'libclang.so.*' -type f | head -1 || true)"
  if [ -n "$real" ]; then
    ln -sf "$(basename "$real")" "${prefix}/lib/libclang.so"
  fi
fi

# Fail loudly here rather than letting CMake silently fall back to the stub.
test -f "${prefix}/include/clang-c/Index.h" \
  || { echo "fetch-libclang: clang-c/Index.h missing" >&2; exit 1; }
test -e "${prefix}/lib/libclang.so" \
  || { echo "fetch-libclang: libclang.so missing" >&2; exit 1; }

echo "fetch-libclang: installed libclang ${ver} (${arch}) to ${prefix}" >&2
ls -l "${prefix}/lib/"libclang.so* >&2
