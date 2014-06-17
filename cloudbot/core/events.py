import asyncio
import logging
import concurrent.futures

logger = logging.getLogger("cloudbot")


class BaseEvent:
    """
    :type bot: cloudbot.core.bot.CloudBot
    :type conn: cloudbot.core.connection.BotConnection
    :type hook: cloudbot.core.pluginmanager.Hook
    :type nick: str
    :type user: str
    :type host: str
    :type mask: str
    :type db: sqlalchemy.orm.Session
    :type db_executor: concurrent.futures.ThreadPoolExecutor
    :type irc_message: str
    :type irc_raw: str
    :type irc_prefix: str
    :type irc_command: str
    :type irc_paramlist: str
    """

    def __init__(self, *, bot=None, hook=None, conn=None, base_event=None, irc_message=None, nick=None, user=None,
                 host=None, mask=None, irc_raw=None, irc_prefix=None, irc_command=None, irc_paramlist=None):
        """
        All of these parameters except for *bot* and *hook* are optional, *bot* may be left out when using base_event.

        :param bot: The CloudBot instance this event was triggered from
        :param conn: The Connection instance this event was triggered from
        :param hook: The hook this event will be passed to
        :param base_event: The base event that this event is based on. If this parameter is not None, then nick, user,
                            host, mask, and irc_* arguments are ignored
        :param nick: The nickname of the sender that triggered this event
        :param user: The user of the sender that triggered this event
        :param host: The host of the sender that triggered this event
        :param mask: The mask of the sender that triggered this event (nick!user@host)
        :param irc_raw: The raw IRC line
        :param irc_prefix: The raw IRC prefix
        :param irc_command: The IRC command
        :param irc_paramlist: The list of params for the IRC command. If the last param is a content param, the ':'
                                should be removed from the front.
        :param irc_message: The content of the message, or the reason for an join or part
        :type bot: cloudbot.core.bot.CloudBot
        :type conn: cloudbot.core.connection.BotConnection
        :type hook: cloudbot.core.pluginmanager.Hook
        :type base_event: cloudbot.core.events.BaseEvent
        :type nick: str
        :type user: str
        :type host: str
        :type mask: str
        :type irc_message: str
        :type irc_raw: str
        :type irc_prefix: str
        :type irc_command: str
        :type irc_paramlist: list[str]
        """
        self.db = None
        self.db_executor = None
        self.bot = bot
        self.conn = conn
        self.hook = hook
        if base_event is not None:
            # We're copying an event, so inherit values
            if self.bot is None and base_event.bot is not None:
                self.bot = base_event.bot
            if self.conn is None and base_event.conn is not None:
                self.conn = base_event.conn
            if self.hook is None and base_event.hook is not None:
                self.hook = base_event.hook

            # inherit nick/usr/host/mask/irc_* without checking internal values, as we always want to inherit these
            self.nick = base_event.nick
            self.user = base_event.user
            self.host = base_event.host
            self.mask = base_event.mask
            self.irc_message = base_event.irc_message
            self.irc_raw = base_event.irc_raw
            self.irc_prefix = base_event.irc_prefix
            self.irc_command = base_event.irc_command
            self.irc_paramlist = base_event.irc_paramlist
        else:
            # if we're not inheriting an event, we can take these parameters
            self.irc_message = irc_message
            self.irc_raw = irc_raw
            self.irc_prefix = irc_prefix
            self.irc_command = irc_command
            self.irc_paramlist = irc_paramlist
            self.nick = nick
            self.user = user
            self.host = host
            self.mask = mask

    @asyncio.coroutine
    def prepare(self):
        """
        Initializes this event to be run through it's hook

        Mainly, initializes a database object on this event, if the hook requires it.

        This method is for when the hook is *not* threaded (event.hook.threaded is False).
        If you need to add a db to a threaded hook, use prepare_threaded.
        """

        if self.hook is None:
            raise ValueError("event.hook is required to prepare an event")

        if "db" in self.hook.required_args:
            logger.debug("Opening database session for {}:threaded=False".format(self.hook.description))

            # we're running a coroutine hook with a db, so initialise an executor pool
            self.db_executor = concurrent.futures.ThreadPoolExecutor(1)
            # be sure to initialize the db in the database executor, so it will be accessible in that thread.
            self.db = yield from self.async(self.bot.db_session)

    def prepare_threaded(self):
        """
        Initializes this event to be run through it's hook

        Mainly, initializes the database object on this event, if the hook requires it.

        This method is for when the hook is threaded (event.hook.threaded is True).
        If you need to add a db to a coroutine hook, use prepare.
        """

        if self.hook is None:
            raise ValueError("event.hook is required to prepare an event")

        if "db" in self.hook.required_args:
            logger.debug("Opening database session for {}:threaded=True".format(self.hook.description))

            self.db = self.bot.db_session()

    @asyncio.coroutine
    def close(self):
        """
        Closes this event after running it through it's hook.

        Mainly, closes the database connection attached to this event (if any).

        This method is for when the hook is *not* threaded (event.hook.threaded is False).
        If you need to add a db to a threaded hook, use close_threaded.
        """
        if self.hook is None:
            raise ValueError("event.hook is required to close an event")

        if self.db is not None:
            logger.debug("Closing database session for {}:threaded=False".format(self.hook.description))
            # be sure the close the database in the database executor, as it is only accessable in that one thread
            yield from self.async(self.db.close)
            self.db = None

    def close_threaded(self):
        """
        Closes this event after running it through it's hook.

        Mainly, closes the database connection attached to this event (if any).

        This method is for when the hook is threaded (event.hook.threaded is True).
        If you need to add a db to a coroutine hook, use close.
        """
        if self.hook is None:
            raise ValueError("event.hook is required to close an event")
        if self.db is not None:
            logger.debug("Closing database session for {}:threaded=True".format(self.hook.description))
            self.db.close()
            self.db = None

    @property
    def server(self):
        """
        :rtype: str
        """
        if self.conn is not None:
            return self.conn.server
        else:
            return None

    @property
    def chan(self):
        """
        :rtype: str
        """
        if self.irc_paramlist:
            if self.irc_paramlist[0].lower() == self.conn.nick.lower():
                # this is a private message - set the nick to the sender's nick
                return self.nick.lower()
            else:
                return self.irc_paramlist[0].lower()
        else:
            return None

    @property
    def event(self):
        """
        :rtype; cloudbot.core.events.BaseEvent
        """
        return self

    @property
    def loop(self):
        """
        :rtype: asyncio.events.AbstractEventLoop
        """
        return self.bot.loop

    @property
    def logger(self):
        return logger

    def message(self, message, target=None):
        """sends a message to a specific or current channel/user
        :type message: str
        :type target: str
        """
        if target is None:
            if self.chan is None:
                raise ValueError("Target must be specified when chan is not assigned")
            target = self.chan
        self.conn.msg(target, message)

    def reply(self, message, target=None):
        """sends a message to the current channel/user with a prefix
        :type message: str
        :type target: str
        """
        if target is None:
            if self.chan is None:
                raise ValueError("Target must be specified when chan is not assigned")
            target = self.chan

        if target == self.nick:
            self.conn.msg(target, message)
        else:
            self.conn.msg(target, "({}) {}".format(self.nick, message))

    def action(self, message, target=None):
        """sends an action to the current channel/user or a specific channel/user
        :type message: str
        :type target: str
        """
        if target is None:
            if self.chan is None:
                raise ValueError("Target must be specified when chan is not assigned")
            target = self.chan

        self.conn.ctcp(target, "ACTION", message)

    def ctcp(self, message, ctcp_type, target=None):
        """sends an ctcp to the current channel/user or a specific channel/user
        :type message: str
        :type ctcp_type: str
        :type target: str
        """
        if target is None:
            if self.chan is None:
                raise ValueError("Target must be specified when chan is not assigned")
            target = self.chan
        self.conn.ctcp(target, ctcp_type, message)

    def notice(self, message, target=None):
        """sends a notice to the current channel/user or a specific channel/user
        :type message: str
        :type target: str
        """
        if target is None:
            if self.nick is None:
                raise ValueError("Target must be specified when nick is not assigned")
            target = self.nick

        self.conn.cmd('NOTICE', [target, message])

    def has_permission(self, permission, notice=True):
        """ returns whether or not the current user has a given permission
        :type permission: str
        :rtype: bool
        """
        if not self.mask:
            raise ValueError("has_permission requires mask is not assigned")
        return self.conn.permissions.has_perm_mask(self.mask, permission, notice=notice)

    @asyncio.coroutine
    def async(self, function, *args, **kwargs):
        if self.db_executor is not None:
            executor = self.db_executor
        else:
            executor = None
        if kwargs:
            result = yield from self.loop.run_in_executor(executor, function, *args)
        else:
            result = yield from self.loop.run_in_executor(executor, lambda: function(*args, **kwargs))
        return result


class CommandEvent(BaseEvent):
    """
    :type hook: cloudbot.core.pluginmanager.CommandHook
    :type text: str
    :type triggered_command: str
    """

    def __init__(self, *, bot=None, hook, text, triggered_command, conn=None, base_event=None, irc_message=None,
                 nick=None, user=None, host=None, mask=None, irc_raw=None, irc_prefix=None, irc_command=None,
                 irc_paramlist=None):
        """
        :param text: The arguments for the command
        :param triggered_command: The command that was triggered
        :type text: str
        :type triggered_command: str
        """
        super().__init__(bot=bot, hook=hook, conn=conn, base_event=base_event, nick=nick, user=user, host=host,
                         mask=mask, irc_message=irc_message, irc_raw=irc_raw, irc_prefix=irc_prefix,
                         irc_command=irc_command, irc_paramlist=irc_paramlist)
        self.hook = hook
        self.text = text
        self.triggered_command = triggered_command

    def notice_doc(self, target=None):
        """sends a notice containing this command's docstring to the current channel/user or a specific channel/user
        :type target: str
        """
        if self.triggered_command is None:
            raise ValueError("Triggered command not set on this event")
        if self.hook.doc is None:
            message = "{}{} requires additional arguments.".format(self.conn.config["command_prefix"],
                                                                   self.triggered_command)
        else:
            if self.hook.doc.split()[0].isalpha():
                # this is using the old format of `name <args> - doc`
                message = "{}{}".format(self.conn.config["command_prefix"], self.hook.doc)
            else:
                # this is using the new format of `<args> - doc`
                message = "{}{} {}".format(self.conn.config["command_prefix"], self.triggered_command, self.hook.doc)

        self.notice(message, target=target)


class RegexEvent(BaseEvent):
    """
    :type hook: cloudbot.core.pluginmanager.RegexHook
    :type match: re.__Match
    """

    def __init__(self, *, bot=None, hook, match, conn=None, base_event=None, irc_message=None, nick=None, user=None,
                 host=None, mask=None, irc_raw=None, irc_prefix=None, irc_command=None, irc_paramlist=None):
        """
        :param: match: The match objected returned by the regex search method
        :type match: re.__Match
        """
        super().__init__(bot=bot, conn=conn, hook=hook, base_event=base_event, nick=nick, user=user, host=host,
                         mask=mask, irc_message=irc_message, irc_raw=irc_raw, irc_prefix=irc_prefix,
                         irc_command=irc_command, irc_paramlist=irc_paramlist)
        self.match = match
