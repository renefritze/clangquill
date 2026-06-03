# Namespace `geo`

Geometry primitives.

## Class `geo::Shape`

```{cpp:class} geo::Shape

Abstract base for shapes.
```

## Class `geo::Circle`

**Inherits from** {cpp:any}`geo::Shape`.

```{cpp:class} geo::Circle : public Shape

A circle.

Defined by its radius.

:::{note}
The radius must be positive.
:::
```

```{cpp:function} double geo::Circle::area() const

Compute the area.

:returns: the area in square units.
```

```{cpp:member} double geo::Circle::radius

The radius of the circle.
```

```{cpp:function} Circle geo::scale(const Circle &c, double factor)

Return a scaled copy of a circle.

**See also:** {cpp:any}`geo::Circle`

:param c: the circle to scale
:param factor: the scale factor
:returns: a new, scaled circle.
```

```{cpp:function} void geo::mystery()

*No documentation provided.*
```

```{cpp:var} const double geo::pi

The circle constant.
```

```{cpp:enum} geo::Color

A named drawing color.
```

```{cpp:enumerator} geo::Color::Red
```

```{cpp:enumerator} geo::Color::Green
```

```{cpp:enumerator} geo::Color::Blue
```

```{cpp:type} geo::Distance = double

A distance in meters.
```
