#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

namespace clangquill::hash {

// Minimal streaming SHA-256. Vendored to avoid an OpenSSL dependency and keep
// the wheel small (see ADR 0001).
class Sha256 {
 public:
  Sha256();
  void update(std::string_view data);
  void update(const void* data, std::size_t len);
  // Returns the lowercase hex digest and resets the state.
  std::string hexdigest();

 private:
  void transform(const std::uint8_t* chunk);

  std::uint32_t state_[8];
  std::uint64_t bit_len_ = 0;
  std::uint8_t buffer_[64];
  std::size_t buffer_len_ = 0;
};

// Convenience: hex SHA-256 of a buffer.
std::string sha256_hex(std::string_view data);

}  // namespace clangquill::hash
