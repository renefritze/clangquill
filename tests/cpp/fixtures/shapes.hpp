#pragma once

/// A 2D geometry namespace.
namespace geo {

/// Base shape interface.
struct Shape {
  /// Compute the area.
  /// @return the area in square units
  virtual double area() const = 0;
};

/**
 * A circle shape.
 * @param r the radius
 */
class Circle : public Shape {
 public:
  /// Construct a circle of the given radius.
  explicit Circle(double r);

  double area() const override;

 private:
  double radius_;  // intentionally undocumented
};

}  // namespace geo
