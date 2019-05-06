from . import bridge

""" Use this list to exclude modules and names loaded by the remote ghidra_bridge side from being loaded into our namespace.
This prevents the ghidra_bridge imported by ghidra_bridge_server being loaded over the local ghidra_bridge and causing issues.
You probably only want this for stuff imported by the ghidra_bridge_server script that might conflict on the local side (or which
is totally unnecessary on the local side, like GhidraBridgeServer).
"""
EXCLUDED_REMOTE_IMPORTS = ["logging", "subprocess",
                           "ghidra_bridge", "bridge", "GhidraBridgeServer"]

GHIDRA_BRIDGE_NAMESPACE_TRACK = "__ghidra_bridge_namespace_track__"


class GhidraBridge():
    def __init__(self, connect_to_host=bridge.DEFAULT_HOST, connect_to_port=bridge.DEFAULT_SERVER_PORT, loglevel=None, namespace=None, interactive_mode=True):
        """ Set up a bridge. Default settings connect to the default ghidra bridge server,

        If namespace is specified (e.g., locals() or globals()), automatically calls get_flat_api() with that namespace. 

        loglevel for what logging messages you want to capture

        interactive_mode should auto-detect interactive environments (e.g., ipython or not in a script), but 
        you can force it to True or False if you need to. False is normal ghidra script behaviour 
        (currentAddress/getState() etc locked to the values when the script started. True is closer to the 
        behaviour in the Ghidra Jython shell - current*/getState() reflect the current values in the GUI
        """
        self.bridge = bridge.BridgeClient(
            connect_to_host=connect_to_host, connect_to_port=connect_to_port, loglevel=loglevel)

        self.interactive_mode = interactive_mode
        self.interactive_listener = None

        self.namespace = None
        if namespace is not None:
            if connect_to_host is None or connect_to_port is None:
                raise Exception(
                    "Can't get_flat_api for the namespace if connect_to_host/port are none - need a server!")

            # track the namespace we loaded with - if we're part of an __enter__/__exit__ setup, we'll use it to automatically unload the flat api
            self.namespace = namespace
            self.get_flat_api(namespace=self.namespace)

    def get_flat_api(self, namespace=None):
        """ Get the flat API (as well as the GhidraScript API). If a namespace is provided (e.g., locals() or globals()), load the methods and
        fields from the APIs into that namespace (call unload_flat_api() to remove). Otherwise, just return the bridged module.

        Note that the ghidra and java packages are always loaded into the remote script's side, so get_flat_api with namespace will get the
        ghidra api and java namespace for you for free.
        """

        remote_main = self.bridge.remote_import("__main__")

        if self.interactive_mode:
            if self.interactive_listener is None:
                # define the interactive listener here, because we need the remote ghidra object

                # this fails because it's expecting a type, not a BridgedObject. BridgedObject.__init__ is getting called, not type.__init__(self, /, args, kwargs)
                # could we simply fake this? add an extra arg to the bridgedobject init and see?
                class InteractiveListener(remote_main.ghidra.framework.model.ToolListener):
                    def __init__(self, tool):
                        self.tool = tool
                        self.update_list = []

                        # register the listener against the remote tool
                        tool.addToolListener(self)

                    def __del__(self):
                        # we're done, make sure we remove the tool listener
                        self.tool.removeToolListener(self)

                    def add_to_update_list(self, namespace):
                        self.update_list.append(namespace)

                    def processToolEvent(self, plugin_event):
                        """ Called by the ToolListener interface """
                        print("hi!")
                        print(plugin_event)

                x = remote_main.ghidra.framework.model.ToolListener

                tool = remote_main.state.getTool()
                self.interactive_listener = InteractiveListener(tool)

        if namespace is not None:
            # add a special var to the namespace to track what we add, so we can remove it easily later
            namespace[GHIDRA_BRIDGE_NAMESPACE_TRACK] = dict()

            # load in all the attrs from remote main, skipping the double underscores and avoiding overloading our own ghidra_bridge
            for attr in remote_main._bridge_attrs:
                if not attr.startswith("__") and attr not in EXCLUDED_REMOTE_IMPORTS:
                    remote_attr = getattr(remote_main, attr)
                    namespace[attr] = remote_attr
                    # record what we added to the namespace
                    namespace[GHIDRA_BRIDGE_NAMESPACE_TRACK][attr] = remote_attr

        return remote_main

    def unload_flat_api(self, namespace=None):
        """ If get_flat_api was called with a namespace and loaded methods/fields into it, unload_flat_api will remove them.
            Note: if the values don't match what was loaded, we assume the caller has modified for their own reasons, and leave alone.
        """
        if namespace is None:
            if self.namespace is None:
                raise Exception(
                    "Bridge wasn't initialized with a namespace - need to specify the namespace you want to unload from")
            namespace = self.namespace

        if GHIDRA_BRIDGE_NAMESPACE_TRACK in namespace:
            for key, value in namespace[GHIDRA_BRIDGE_NAMESPACE_TRACK].items():
                if key in namespace:
                    if namespace[key] == value:
                        del namespace[key]
        else:
            raise Exception(GHIDRA_BRIDGE_NAMESPACE_TRACK +
                            " not present in namespace - get_flat_api() didn't load into this namespace")

    def get_ghidra_api(self):
        """ get the ghidra api - `ghidra = bridge.get_ghidra_api()` equivalent to doing `import ghidra` in your script.
            Note that the module returned from get_flat_api() will also contain the ghidra module, so you may not need to call this.
        """
        return self.bridge.remote_import("ghidra")

    def get_java_api(self):
        """ get the java namespace - `java = bridge.get_java_api()` equivalent to doing `import java` in your script.
            Note that the module returned from get_flat_api() will also contain the java module, so you may not need to call this.
        """
        return self.bridge.remote_import("java")

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        if self.namespace is not None:
            self.unload_flat_api(self.namespace)
