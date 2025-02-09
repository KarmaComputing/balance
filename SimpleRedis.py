from multiprocessing import shared_memory


class SimpleRedis:

    def __init__(self):

        self.SHARED_MEMORY_LENGTH_BYTES = 256

        try:
            self.shm = shared_memory.SharedMemory(
                create=True,
                size=self.SHARED_MEMORY_LENGTH_BYTES,
                name="simple_redis",  # noqa: E501
            )
            print("Created new shared memory")
        except FileExistsError as e:
            print(f"Got {e}. So re-using existing shared memory")
            self.shm = shared_memory.SharedMemory(
                create=False,
                size=self.SHARED_MEMORY_LENGTH_BYTES,
                name="simple_redis",  # noqa: E501
            )

    def put(self, value: bytes):
        """Put into shared memory"""
        # Verify of type bytes
        if not isinstance(value, bytes):
            msg = (
                "You must pass a value of type bytes. "
                "Tip: use variable.encode('utf-8') to encode strings to bytes"
            )
            raise Exception(msg)
        # Get length of value
        value_size = len(value)
        # Validate length of value is <= SHARED_MEMORY_LENGTH_BYTES
        if value_size > self.SHARED_MEMORY_LENGTH_BYTES:
            raise Exception(
                f"Refusing to put value larger than SHARED_MEMORY_LENGTH_BYTES: {self.SHARED_MEMORY_LENGTH_BYTES}"  # noqa: E501
            )

        # Clear current shared memory
        self.free()
        # Store value in shared memory
        self.shm.buf[:value_size] = value

    def read(self, parse_int=False) -> bytes | int:
        """Prints & returns contents of shared memory

        parse_int: bool Try to parse shared memory value into an int
                   and return it. Default false.
        """
        if parse_int:
            contents = int(self.read().decode("utf-8").rstrip("\x00"))
        else:
            contents = bytes(self.shm.buf)
        return contents

    def debug_shm(self):
        """Puts a debug string into the shared memory & prints it"""

        self.shm.buf[:] = b"hello12345"
        print(bytes(self.shm.buf))

    def free(self):
        """Clears the shared memory and set it all to
        empty bytes (\x00\00) of lenth
        SHARED_MEMORY_LENGTH_BYTES
        Essentially calloc.
        """
        self.shm.buf[:] = bytes(self.SHARED_MEMORY_LENGTH_BYTES)

    def destroy(self):
        """Destroy the shared memory"""
        self.shm.close()
        self.shm.unlink()

    def __del__(self):
        pass
        # self.shm.close()
        # self.shm.unlink()  # Probably not needed/here be dragons
        # Who decides when we don't need the shared memory :)


simple_redis = SimpleRedis()
