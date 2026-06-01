#pragma once

namespace doc {

/**
 * Computes the quotient of two integers.
 *
 * Performs integer division and reports failure via an exception. This second
 * paragraph is detail text.
 *
 * @param numerator the value to divide
 * @param denominator the divisor; must not be zero
 * @return the integer quotient
 * @retval 0 when the numerator is zero
 * @throws std::domain_error if @p denominator is zero
 * @note rounding follows truncation toward zero
 * @warning undefined for INT_MIN / -1
 * @since 1.2
 * @see multiply
 * @author Ada
 */
int divide(int numerator, int denominator);

/// @brief Multiplies two values.
/// @tparam T an arithmetic type
/// @param a first factor
/// @param b second factor
/// @return the product
template <typename T>
T multiply(T a, T b);

/// @deprecated use divide instead
int old_divide(int a, int b);

/**
 * Squares a value.
 * @code
 *   int y = square(3); // y == 9
 * @endcode
 */
int square(int x);

}  // namespace doc
