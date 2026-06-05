#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

/**
 * @file
 * @brief Minimal vendored SHA-256 implementation.
 */

namespace clangquill::hash {

/// @brief Minimal streaming SHA-256.
///
/// Vendored to avoid an OpenSSL dependency and keep the wheel small (see
/// ADR 0001). Feed bytes with @ref update and finalize with @ref hexdigest.
class Sha256 {
 public:
  Sha256();

  /// @brief Feeds a string view of bytes into the digest.
  /// @param data The bytes to hash.
  void update(std::string_view data);

  /// @brief Feeds a raw buffer into the digest.
  /// @param data Pointer to the bytes to hash.
  /// @param len Number of bytes to read from @p data.
  void update(const void* data, std::size_t len);

  /// @brief Finalizes the digest, returning it and resetting the state.
  /// @return The lowercase hex digest.
  std::string hexdigest();

 private:
  void reset();
  void transform(const std::uint8_t* chunk);

  std::uint32_t state_[8];
  std::uint64_t bit_len_ = 0;
  std::uint8_t buffer_[64];
  std::size_t buffer_len_ = 0;
};

/// @brief Convenience helper: hex SHA-256 of a single buffer.
/// @param data The bytes to hash.
/// @return The lowercase hex digest of @p data.
std::string sha256_hex(std::string_view data);

}  // namespace clangquill::hash
