class Bean(object):
    """
    POJO属性对象

    .. 用法示例：
        class Foo(Simple):
            __slots__ = ('x', 'y', 'z')

            def __init__(self, **kwargs):
                super().__init__(**kwargs)
    """
    __slots__ = ()

    def __init__(self, **kwargs):
        for k in kwargs.fromkeys(self.__slots__):
            if k in kwargs:
                setattr(self, k, kwargs[k])
            else:
                setattr(self, k, None)

    @property
    def json(self):
        return {s: getattr(self, s) for s in self.__slots__ if hasattr(self, s)}


class JsonBean:

    def _json(self):
        return {s: getattr(self, s) for s in self.__slots__ if hasattr(self, s)}
