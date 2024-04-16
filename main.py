import disnake
from disnake.ext import commands, tasks
import json
import time
import asyncio
import os
import pymongo
import aiohttp
import sys
import requests

client = commands.InteractionBot()
dbclient = pymongo.MongoClient(
    "mongodb+srv://mongo:"
    + os.environ["MONGO_PASSWORD"]
    + "@games.tyn0n.mongodb.net/myFirstDatabase?retryWrites=true&w=majority"
)


client.DATABASE = dbclient["test"]


# This is so I can get information from the server asynchronously
async def fetch(session, url):
    async with session.get(url) as response:
        return str(await response.text())


async def findgames(session, gameids, playerid, usercount=0, lastGameId=None):
    if lastGameId == None:
        response = json.loads(
            await (
                await session.get(
                    f"https://www.twilightwars.com/find-a-game/search?status=Active"
                )
            ).text()
        )
    else:
        response = json.loads(
            await (
                await session.get(
                    f"https://www.twilightwars.com/find-a-game/search?status=Active&lastGameId="
                    + lastGameId
                )
            ).text()
        )

    for game in response["games"]:
        for player in game["players"]:
            if player["user"] != None:
                if playerid in player["user"]["_id"]:
                    gameids.append(game)

        for user in game["players"]:
            usercount += 1
    if response["canSeeMore"]:
        gameids = await findgames(
            session, gameids, playerid, usercount, response["games"][-1]["_id"]
        )
    return gameids


@client.slash_command(
    name="quicknotify",
    description="Get notifications for every public game you are part of. May take up to one minute.",
)
async def quicknotify(ctx):
    author = ctx.author.id
    await ctx.response.defer()

    try:

        default = client.DATABASE["user"].find_one({"auid": str(author)})
        if default == None:
            await ctx.send(
                "Because this is the first time you are using this command, please use /setdefault to change your default settings"
            )
            return

        games = await findgames(client.session, list(), default["TWUser"])
        for game in games:
            gameurl = "https://www.twilightwars.com/games/" + game["_id"]
            log, gamesummary, players = [
                json.loads(x)
                for x in await asyncio.gather(
                    fetch(client.session, gameurl + "/log"),
                    fetch(client.session, gameurl + "/summary"),
                    fetch(client.session, gameurl + "/players"),
                )
            ]
            await setnotification(
                default["TWUser"], gameurl, log, gamesummary, players, str(author)
            )
            await changesettings(
                default["settings"].split(","),
                gameurl,
                str(author),
                ctx,
                default["TWUser"],
            )

        embed = await outputnotifications(str(author))
        await ctx.followup.send("These are your current notifications:", embed=embed)
    except:
        print("Some error detected")
        await ctx.channel.send("Unable to find games, trying again.")
        await asyncio.sleep(20)
        try:
            default = client.DATABASE["user"].find_one({"auid": str(author)})
            if default == None:
                await ctx.send("Please use /setdefault to change your default settings")
                return

            games = await findgames(client.session, list(), default["TWUser"])
            for game in games:
                gameurl = "https://www.twilightwars.com/games/" + game["_id"]
                log, gamesummary, players = [
                    json.loads(x)
                    for x in await asyncio.gather(
                        fetch(client.session, gameurl + "/log"),
                        fetch(client.session, gameurl + "/summary"),
                        fetch(client.session, gameurl + "/players"),
                    )
                ]
                await setnotification(
                    default["TWUser"], gameurl, log, gamesummary, players, str(author)
                )
                await changesettings(
                    default["settings"].split(","),
                    gameurl,
                    str(author),
                    ctx,
                    default["TWUser"],
                )

            embed = await outputnotifications(str(author))
            await ctx.followup.send(
                "These are your current notifications:", embed=embed
            )
        except:
            await ctx.channel.send(
                "Unable to connect to twilightwars right now, please use /bulknotify."
            )
            raise


# This is the command that creates an embed with each notification on it. It basically does nothing but hand it off to another function, this is because a number of other commands have the same functionality
@client.slash_command(
    name="viewnotifications",
    description="Provides a list of all notifications",
    options=[],
)
async def view(ctx):
    await ctx.response.defer()
    embed = await outputnotifications(str(ctx.author.id))
    await ctx.followup.send("Notifications: ", embed=embed)


async def changedefault(ctx, gameurl):
    defaultdic = {
        "auid": str(ctx.author.id),
        "settings": "",
        "TWUser": "",
        "TWUsername": "",
    }

    async def finish(interaction: disnake.MessageInteraction):
        if interaction.author.id == ctx.author.id:
            # This locks the select box so you can't use it twice, while updating thpe default dictionary with your settings
            await interaction.response.defer()
            a = await interaction.original_message()
            select = disnake.ui.Select(
                placeholder=",".join(interaction.values),
                options=[disnake.SelectOption(label="HMM")],
                disabled=True,
            )
            view = disnake.ui.View()
            view.add_item(select)
            await interaction.followup.edit_message(message_id=a.id, view=view)
            answer = 0
            values = interaction.values
            defaultdic["settings"] = ",".join(interaction.values)

            # This creates another select menu with the TW Usernames
            async def usercallback(interaction: disnake.MessageInteraction):
                # Locks the thingy
                await interaction.response.defer()
                a = await interaction.original_message()
                select = disnake.ui.Select(
                    placeholder=",".join(interaction.values),
                    options=[disnake.SelectOption(label="HMM")],
                    disabled=True,
                )
                view = disnake.ui.View()
                view.add_item(select)
                await interaction.followup.edit_message(message_id=a.id, view=view)
                usercallback.trackedplayers = interaction.values
                # Creates the different players

            async with client.session.get(gameurl + "/players") as players:
                try:
                    playeroptions = [
                        (x["user"]["username"].strip(" "), x["user"]["_id"])
                        for x in json.loads(await players.text())
                    ]
                    if playeroptions == None or playeroptions == []:
                        raise ()
                except:
                    await interaction.followup.send(gameurl + " could not be found")
                    return
                options = [
                    disnake.SelectOption(
                        label=x["user"]["username"].strip(" "), value=x["user"]["_id"]
                    )
                    for x in json.loads(await players.text())
                ]
            select = disnake.ui.Select(options=options, min_values=1, max_values=1)
            select.callback = usercallback
            view = disnake.ui.View()
            view.add_item(select)
            await ctx.followup.send("Please choose your username: ", view=view)
            timeout = 600
            while "trackedplayers" not in dir(usercallback) and timeout > 0:
                await asyncio.sleep(0.1)
                timeout -= 1
            # Just changes the default dictionary which can then be stored in MongoDB
            defaultdic["TWUser"] = usercallback.trackedplayers[0]
            defaultdic["TWUsername"] = [
                x[0] for x in playeroptions if x[1] == usercallback.trackedplayers[0]
            ][0]
            if client.DATABASE["user"].find_one({"auid": str(ctx.author.id)}) == None:
                client.DATABASE["user"].insert_one(defaultdic)
            else:
                client.DATABASE["user"].replace_one(
                    {"auid": str(ctx.author.id)}, defaultdic
                )
            embed = await outputnotifications(str(ctx.author.id))
            await ctx.followup.send("These are your current notifications", embed=embed)
            return defaultdic
            games[gameurl][User][ctx.author.id] == answer

        else:
            await interaction.response.defer()
            await ctx.followup.send("You are not the original author")
        finish.done = True

    noptions = [
        "Notify when game is waiting on you (default)",
        "Notify after every change of window",
        "Notify when Trade is played",
        "Notify when a Strategy Card is played",
        "Notify when game log updates",
        "Remove notification",
    ]
    noptions = [
        disnake.SelectOption(label=x[1], value=x[0]) for x in enumerate(noptions)
    ]
    select = disnake.ui.Select(
        placeholder="Pick a setting: ",
        options=noptions,
        min_values=1,
        max_values=len(noptions) - 1,
    )
    select.callback = finish
    view = disnake.ui.View(timeout=300)
    view.add_item(select)
    await ctx.followup.send("Select all settings that apply (scroll down)", view=view)


@client.slash_command(
    name="removeall",
    description="This will delete every notification that you have",
    options=[
        disnake.Option(
            name="confirmation",
            description="Would you like to remove all notifications Y/N",
            required=True,
        )
    ],
)
async def removeall(ctx, confirmation):
    # Simply loops through every stored game and removes ctx.author.id
    await ctx.response.defer()
    if "y" == confirmation.lower():
        games = client.DATABASE["games"].find()
        for ngame in games:
            value = []
            if str(ctx.author.id) in ngame["users"].split(","):
                await changesettings(
                    "5", ngame["gameurl"], str(ctx.author.id), ctx, "0"
                )
        embed = await outputnotifications(str(ctx.author.id))
        await ctx.followup.send("Your notifications have been deleted", embed=embed)
    else:
        await ctx.followup.send("Confirmation must be 'Y' or 'y'")


# Ignore quicknotify, nobody uses it anyway so you can just pretend it doesn't exist.
@client.slash_command(
    name="bulknotify",
    description="Use default settings to add notificati#ons",
    options=[
        disnake.Option(
            name="gameurl1", description="Please paste a game url", required=True
        )
    ]
    + [
        disnake.Option(
            name="gameurl" + str(x),
            description="You may enter more urls",
            required=False,
        )
        for x in range(2, 26)
    ],
)
async def bulknotify(
    ctx,
    gameurl1,
    gameurl2=None,
    gameurl3=None,
    gameurl4=None,
    gameurl5=None,
    gameurl6=None,
    gameurl7=None,
    gameurl8=None,
    gameurl9=None,
    gameurl10=None,
    gameurl11=None,
    gameurl12=None,
    gameurl13=None,
    gameurl14=None,
    gameurl15=None,
    gameurl16=None,
    gameurl17=None,
    gameurl18=None,
    gameurl19=None,
    gameurl20=None,
    gameurl21=None,
    gameurl22=None,
    gameurl23=None,
    gameurl24=None,
    gameurl25=None,
):
    await ctx.response.defer()
    gameurls = [
        gameurl1,
        gameurl2,
        gameurl3,
        gameurl4,
        gameurl5,
        gameurl6,
        gameurl7,
        gameurl8,
        gameurl9,
        gameurl10,
        gameurl11,
        gameurl12,
        gameurl13,
        gameurl14,
        gameurl15,
        gameurl16,
        gameurl17,
        gameurl18,
        gameurl19,
        gameurl20,
        gameurl21,
        gameurl22,
        gameurl23,
        gameurl24,
        gameurl25,
    ]
    gameurls = [x for x in gameurls if x != None]
    default = client.DATABASE["user"].find_one({"auid": str(ctx.author.id)})
    if default == None:
        await ctx.followup.send(
            "No default notification found. Please update your settings in the select boxes below."
        )
        default = await changedefault(ctx, gameurl1)
    timeout = 600
    while default == None and timeout > 0:
        await asyncio.sleep(1)
        timeout -= 1

    async def onegame(gameurl):
        try:
            log, gamesummary, players = [
                json.loads(x)
                for x in await asyncio.gather(
                    fetch(client.session, gameurl + "/log"),
                    fetch(client.session, gameurl + "/summary"),
                    fetch(client.session, gameurl + "/players"),
                )
            ]
        except:
            await ctx.followup.send("Could not find " + gameurl)
            await ctx.followup.send(
                f"Please note that the bot cannot find games in the lobby phase."
            )
            return
        playerids = [x["user"]["_id"] for x in players]
        if default["TWUser"] not in playerids:
            if default["TWUser"] == "":
                default["TWUser"] = None
            else:
                await ctx.followup.send(
                    default["TWUsername"]
                    + " is not part of "
                    + gameurl
                    + "\nPlease use /notify for this game"
                )
                return
        await setnotification(
            default["TWUser"], gameurl, log, gamesummary, players, str(ctx.author.id)
        )
        await changesettings(
            default["settings"].split(","),
            gameurl,
            str(ctx.author.id),
            ctx,
            default["TWUser"],
        )

    await asyncio.gather(*[onegame(x) for x in gameurls])
    embed = await outputnotifications(str(ctx.author.id))
    await ctx.followup.send("These are your current notifications:", embed=embed)


# Despite the title, all this does is create an embed with a users notifications on it. It is likely not what you are looking for.
async def outputnotifications(auid):
    embed = disnake.Embed(title="Current notifications")
    notificationtypes = [
        "When game is waiting on you",
        "When the window changes",
        "When Trade is played",
        "When a Strategy Card is played",
        "When the game log updates",
    ]
    default = client.DATABASE["user"].find_one({"auid": auid})
    if default != None:
        embed.add_field(
            name="Default",
            value="Account name: "
            + default["TWUsername"]
            + "\n"
            + "\n".join(
                [notificationtypes[int(x)] for x in default["settings"].split(",")]
            ),
            inline=False,
        )
    games = client.DATABASE["games"].find()
    for ngame in games:
        value = []
        if auid in ngame["users"].split(","):
            for i in range(1, 5):
                if str(i) in ngame.keys():
                    if auid in ngame[str(i)].split(","):
                        value.append(notificationtypes[i])
            for user in ngame["0"].keys():
                if (
                    auid in ngame[str(0)][user].split(",")
                    and "When game is waiting on you" not in value
                ):
                    value.append(notificationtypes[0])
            embed.add_field(
                name=ngame["gamename"], value="\n".join(value), inline=False
            )
    return embed


@client.slash_command(
    name="setdefault",
    description="Sets the default game",
    options=[
        disnake.Option(
            name="gameurl",
            description="Please paste the url of any game you are part of",
            required=True,
        )
    ],
)
async def setdefault(ctx, gameurl):
    await ctx.response.defer()
    await changedefault(ctx, gameurl)


async def changesettings(values, gameurl, auid, ctx, user=None):
    game = client.DATABASE["games"].find_one(
        {"gameurl": gameurl}
    )  # Grabs the dictionary of games for the specific one we are interested in
    for num in list(
        range(5)
    ):  # This loops through the 5 settings and removes the author's id from them
        if num != 0 and str(num) in game.keys():
            game[str(num)] = ",".join(
                [x for x in game[str(num)].split(",") if x != auid]
            )
        elif str(num) in game.keys():
            for userp in game[str(num)].keys():
                game[str(num)][userp] = ",".join(
                    [x for x in game[str(num)][userp].split(",") if x != auid]
                )
    if (
        "0" in values and "1" in values
    ):  # Some settings are incompatible with each other, so if the user selected both of them one is removed
        values.remove("0")
    if "2" in values and "3" in values:
        values.remove("2")
    if (
        "5" not in values
    ):  # If the input we received was "5" then we want to skip all this and remove the user from the system (5 means remove notification)
        for value in values:
            if value != "0":  # If it is not 0 then we just add the user's id on
                if value in game.keys():
                    if game[value] != "":
                        game[value] = game[value] + "," + auid
                    else:
                        game[value] = auid
                else:
                    game[value] = auid
            else:
                if (
                    user == None
                ):  # If it is 0 then we need to create a new interaction asking for which username they would like to be notified for. Fun fact for people reading the code, you can have notifications for two people in one game... just nobody has done it yet that I am aware of. Probably spent too much time accounting for those edge cases than investing in readability, speed and accuracy

                    async def usercallback(interaction: disnake.MessageInteraction):
                        await interaction.response.defer()
                        a = await interaction.original_message()
                        select = disnake.ui.Select(
                            placeholder=",".join(interaction.values),
                            options=[disnake.SelectOption(label="HMM")],
                            disabled=True,
                        )
                        view = disnake.ui.View()
                        view.add_item(select)
                        await interaction.followup.edit_message(
                            message_id=a.id, view=view
                        )

                        usercallback.trackedplayers = interaction.values

                    async with client.session.get(gameurl + "/players") as players:
                        options = [
                            disnake.SelectOption(
                                label=x["user"]["username"].strip(" "),
                                value=x["user"]["_id"],
                            )
                            for x in json.loads(await players.text())
                        ]
                    select = disnake.ui.Select(
                        options=options, min_values=1, max_values=len(options)
                    )
                    select.callback = usercallback
                    view = disnake.ui.View()
                    view.add_item(select)
                    await ctx.followup.send("Please choose your username: ", view=view)
                    timeout = 600  # This is a very clunky timeout system, would not reimplement because it clogs everything else up for the next 5 minutes (not by much but it's still a mess)
                    while "trackedplayers" not in dir(usercallback) and timeout > 0:
                        await asyncio.sleep(0.1)
                        timeout -= 1
                    user = usercallback.trackedplayers
                else:
                    user = [user]
                for userid in user:
                    if userid in game["0"].keys():
                        if game["0"][userid] != "":
                            game["0"][userid] = (
                                game["0"][userid] + "," + auid
                            )  # For each TWID the user's Discord ID is added to the end
                        else:
                            game["0"][userid] = auid
                    else:
                        game["0"][userid] = auid
    else:
        game["users"] = ",".join([x for x in game["users"].split(",") if x != auid])

    client.DATABASE["games"].replace_one({"gameurl": game["gameurl"]}, game)
    return await outputnotifications(auid)


@client.slash_command(name="config", description="Change settings for a game")
async def config(ctx):
    async def contin(interaction: disnake.MessageInteraction):
        async def finish(interaction: disnake.MessageInteraction):
            if interaction.author.id == ctx.author.id:
                await interaction.response.defer()
                a = await interaction.original_message()
                select = disnake.ui.Select(
                    placeholder=",".join(interaction.values),
                    options=[disnake.SelectOption(label="HMM")],
                    disabled=True,
                )
                view = disnake.ui.View()
                view.add_item(select)
                await interaction.followup.edit_message(message_id=a.id, view=view)
                answer = 0
                values = interaction.values
                embed = await changesettings(
                    values, selection[0], str(ctx.author.id), ctx
                )
                await interaction.followup.send(
                    "Your settings have been updated", embed=embed
                )
                # games[gameurl][User][ctx.author.id] == answer

            else:
                await interaction.response.defer()
                await ctx.followup.send("You are not the original author")

        await interaction.response.defer()
        if interaction.author.id == ctx.author.id:
            a = await interaction.original_message()
            select = disnake.ui.Select(
                placeholder=interaction.values[0],
                options=[disnake.SelectOption(label="HMM")],
                disabled=True,
            )
            view = disnake.ui.View()
            view.add_item(select)
            await interaction.followup.edit_message(message_id=a.id, view=view)
            selection = interaction.values
            noptions = [
                "Notify when game is waiting on you (default)",
                "Notify after every change of window",
                "Notify when Trade is played",
                "Notify when a Strategy Card is played",
                "Notify when game log updates",
                "Remove notification",
            ]
            noptions = [
                disnake.SelectOption(label=x[1], value=x[0])
                for x in enumerate(noptions)
            ]
            select = disnake.ui.Select(
                placeholder="Pick a setting: ",
                options=noptions,
                min_values=1,
                max_values=len(noptions) - 1,
            )
            select.callback = finish
            view = disnake.ui.View(timeout=300)
            view.add_item(select)
        else:
            await ctx.followup.send("You are not the original author.")
        await ctx.followup.send(
            "Select all settings that apply (scroll down)", view=view
        )

    await ctx.response.defer(ephemeral=False)
    start = time.time()
    games = client.DATABASE["games"].find()
    options = []
    for game in games:
        if str(ctx.author.id) in game["users"].split(","):
            options.append(
                disnake.SelectOption(
                    label=game["gamename"],
                    description=game["gameurl"],
                    value=game["gameurl"],
                )
            )
    select = disnake.ui.Select(
        placeholder="Pick a notification...",
        min_values=1,
        max_values=1,
        options=options,
    )
    select.callback = contin
    view = disnake.ui.View(timeout=300)
    view.add_item(select)
    first_message = await ctx.followup.send("Please pick a notification", view=view)


async def setnotification(user, gameurl, log, gamesummary, players, auid):
    game = client.DATABASE["games"].find_one({"gameurl": gameurl})
    f = True
    gamename = gamesummary["name"]
    if game == None:  # If the game being requested has never been seen before
        if gamesummary["abilityRound"]["inProgress"]:
            waitingplayer = players[gamesummary["abilityRound"]["current"] - 1]["user"][
                "_id"
            ].strip()
        else:
            waitingplayer = players[gamesummary["turn"]["player"]["current"] - 1][
                "user"
            ][
                "_id"
            ].strip()  # This is just due to some shenanigans on who the game is actually depending on during the ability round
        lst = str(gamesummary["step"]) + str(
            waitingplayer
        )  # This is going to be the check that determines whether the game has progressed or not (If the step is the same and the player is the same, then the states are the same) Theoretically in a small game it might be possible to break this during the ability round where the step doesn't change
        client.DATABASE["games"].insert_one(
            {
                "gameurl": gameurl,
                "lastStep": lst,
                "lastLog": log[0]["_id"],
                "0": {user: auid},
                "users": auid,
                "gamename": gamename,
                "justChanged": lst,
            }
        )  # Creates the database
    else:
        if (
            user in game["0"]
        ):  # Does the same thing but checks if the player already has a notification for them, in which case they are added onto it
            if auid not in game["0"][user].split(","):
                updatedids = ",".join(game["0"][user].split(",") + [auid])
            else:
                updatedids = game["0"][user]
            updatedusers = game["users"]
            if auid not in updatedusers.split(",") and updatedusers != "":
                updatedusers = updatedusers + "," + auid
            elif auid not in updatedusers.split(","):
                updatedusers = auid
            client.DATABASE["games"].update_one(
                {"gameurl": gameurl},
                [{"$set": {"0": {user: updatedids}, "users": updatedusers}}],
            )
        else:
            client.DATABASE["games"].update_one(
                {"gameurl": gameurl}, [{"$set": {"0": {user: auid}}}]
            )
    return gamename  # Some commands need the gamename returned for output


@client.slash_command(
    name="notify",
    description="Receive notifications for a public game",
    options=[
        disnake.Option(
            "gameurl", description="Please paste the url of the game", required=True
        )
    ],
)
async def notify(ctx, gameurl):
    await ctx.response.defer(ephemeral=False)

    async def finish(
        interaction: disnake.MessageInteraction,
    ):  # Just setting up the responses to the select menus (this can probably be done in a more efficient way)
        if interaction.author.id == ctx.author.id:
            await interaction.response.defer()
            a = await interaction.original_message()
            user = interaction.values[0]
            username = [x for x in playeroptions1 if x[1] == user][0][0]
            select = disnake.ui.Select(
                options=[disnake.SelectOption(label="A")],
                disabled=True,
                placeholder=username,
            )
            view = disnake.ui.View()
            view.add_item(select)
            await interaction.followup.edit_message(message_id=a.id, view=view)
            gamename = await setnotification(
                user, gameurl, log, gamesummary, players, str(ctx.author.id)
            )  # Just sends it off to another function
            await ctx.followup.send(
                f"A reminder has been placed in {gamename} for {username}"
            )

        else:
            await interaction.response.send_message(f"You are not the original author")

    try:  # Uses aiohttp to get the information about the game (it does this twice just in case someone only sent the Game ID rather than the URL
        async with client.session.get(gameurl + "/players") as players:
            log, gamesummary, players = [
                json.loads(x)
                for x in await asyncio.gather(
                    fetch(client.session, gameurl + "/log"),
                    fetch(client.session, gameurl + "/summary"),
                    fetch(client.session, gameurl + "/players"),
                )
            ]
            playeroptions1 = [
                (x["user"]["username"].strip(" "), x["user"]["_id"]) for x in players
            ]
            if (
                players == []
            ):  # Just in case either private games get patched or someone sends a valid URL that leads to no game (it is possible)
                raise ()
    except:
        try:
            async with client.session.get(
                "https://www.twilightwars.com/games/" + gameurl + "/players"
            ) as players:
                gameurl = "https://www.twilightwars.com/games/" + gameurl
                log, gamesummary, players = [
                    json.loads(x)
                    for x in await asyncio.gather(
                        fetch(client.session, gameurl + "/log"),
                        fetch(client.session, gameurl + "/summary"),
                        fetch(client.session, gameurl + "/players"),
                    )
                ]
                playeroptions1 = [
                    (x["user"]["username"].strip(" "), x["user"]["_id"])
                    for x in players
                ]
                if players == []:
                    raise ()
        except:
            await ctx.followup.send(f"Could not find: {gameurl}")
            await ctx.followup.send(
                f"Please note that the bot cannot find games in the lobby phase."
            )
            return

    playeroptions = [
        disnake.SelectOption(label=x[0], value=x[1]) for x in playeroptions1
    ]
    select = disnake.ui.Select(
        options=playeroptions,
        placeholder="Choose your TW Account name...",
        min_values=1,
        max_values=1,
    )
    select.callback = finish
    view = disnake.ui.View(timeout=300)
    view.add_item(select)
    await ctx.followup.send("Please pick your Twilight Wars username: ", view=view)


# Does what it says. Not complicated
@client.slash_command(
    name="update", description="Trigger the automatic update immediately"
)
async def updatecommand(ctx):
    await ctx.response.defer()
    if update.is_running():
        update.restart()
    else:
        update.start()
    await ctx.followup.send("Updating...")


@client.slash_command(name="help", description="How to use this bot")
async def help(ctx):
    async def callback(interaction: disnake.MessageInteraction):
        await interaction.response.defer()
        a = await interaction.original_message()
        select = disnake.ui.Select(
            placeholder=["Get Started", "Advanced Commands", "Notification Settings"][
                int(interaction.values[0])
            ],
            options=[
                disnake.SelectOption(label="Get Started", value=0),
                disnake.SelectOption(label="Advanced Commands", value=1),
                disnake.SelectOption(label="Notification Settings", value=2),
            ],
            min_values=1,
            max_values=1,
        )
        select.callback = callback
        view = disnake.ui.View()
        view.add_item(select)
        await interaction.followup.edit_message(
            message_id=a.id, view=view, embed=embeds[int(interaction.values[0])]
        )

    embeds = [
        disnake.Embed(
            title="Help",
            description="""This bot has been designed to mimic the notification system of the Twilight Wars web app for people who are unable to get notifications. Please message Al Vergis if you require any assistance""",
            colour=disnake.Colour.blue(),
        )
        for x in range(3)
    ]
    embeds[0].add_field(
        name="Normal Notify",
        value="To get started type '/notify ' then paste the URL of the game that you want to be monitored. A select menu will appear which will ask you to pick your TW Username. After you have chosen your username, the bot will confirm that the notification has been saved.",
        inline=False,
    )
    embeds[0].add_field(
        name="Bulk Notify",
        value="To add multiple notifications, use '/bulknotify' followed by the URL of a game. If you click the end of the message it will give you the option to add another field to the command, which you can paste the next URL into. You can add between 1 and 25 games using the method.",
        inline=False,
    )
    embeds[0].add_field(
        name="Quick Notify",
        value="To all of your active public games, use '/quicknotify'. The first time you use this, you may be prompted to use /setdefault. Once you have done this, then the bot will search through all public games and notify you when any of them are waiting for you.",
        inline=False,
    )

    embeds[1].add_field(
        name="Advanced Commands",
        value="""There are currently 7 commands:
                          /notify [gameurl]: adds a new notification
                          /quicknotify [gameurls]: allows for multiple games to be added at the same time
                          /config: changes the setting of a notification
                          /viewnotifications: shows current notification settings
                          /update: triggers the automatic update immediately
                          /setdefault [gameurl]: changes your default settings
                          /removeall [confirmation]: removes all notifications""",
        inline=False,
    )
    embeds[2].add_field(
        name="Notification Settings",
        value="""There are 5 settings that can be used with the config command:
                    Notify when game is waiting on you (default)
                    Notify after every change of window
                    Notify when Trade is played
                    Notify when a Strategy Card is played
                    Notify when game log updates""",
        inline=False,
    )
    select = disnake.ui.Select(
        options=[
            disnake.SelectOption(label="Get Started", value=0),
            disnake.SelectOption(label="Advanced commands", value=1),
            disnake.SelectOption(label="Notification Settings", value=2),
        ],
        min_values=1,
        max_values=1,
    )
    select.callback = callback
    view = disnake.ui.View()
    view.add_item(select)
    await ctx.response.send_message("", embed=embeds[0], view=view)


@tasks.loop(minutes=5)
async def update():
    client.deleted = list()
    start = time.time()
    # Starts the timer (for data analysis later) sets up all the colours for the embeds grabs the game database, tells me what loop we are up to
    colours = {
        "magenta": disnake.Colour.magenta(),
        "black": 0,
        "purple": disnake.Colour.purple(),
        "red": disnake.Colour.red(),
        "yellow": disnake.Colour.yellow(),
        "green": disnake.Colour.green(),
        "blue": disnake.Colour.blue(),
        "orange": disnake.Colour.orange(),
    }
    games = client.DATABASE["games"].find()
    print()
    print("Initiating update number: " + str(update.current_loop + 1))
    gamestoberemoved = []
    payload = {
        "email": os.environ["EMAIL"],
        "password": os.environ["PASSWORD"],
    }  # This is for login later
    users = set()

    async def getgames(game):  # This runs
        # print(game)
        for user in game["users"].split(","):
            users.add(user)
        gamename = game["gamename"]
        gameurl = game["gameurl"]
        if "justChanged" not in game.keys():
            game["justChanged"] = ""
        try:
            log, gamesummary, players = [
                json.loads(str(x))
                for x in await asyncio.gather(
                    fetch(client.session, gameurl + "/log"),
                    fetch(client.session, gameurl + "/summary"),
                    fetch(client.session, gameurl + "/players"),
                )
            ]
        except json.decoder.JSONDecodeError:

            peopleinvolved = []
            peopleinvolved = game["users"].split(",")
            client.deleted.append(tuple([gameurl, gamename, peopleinvolved]))
            print(gameurl)
            print(game)
            return
        if game["users"] == "":
            client.DATABASE["games"].delete_one(
                {"gameurl": game["gameurl"]}
            )  # If everyone's removed their notifications from a game, then there's no point in keeping it aroun
        elif (
            log[0]["event"] == "game over"
        ):  # If the game has ended then no point in keeping it around
            peopleinvolved = []
            peopleinvolved = game["users"].split(",")
            await client.channel.send(
                f"<@"
                + "> <@".join(peopleinvolved)
                + ">\n"
                + gamename
                + " has ended, so your notifications have been automatically removed"
            )
            client.DATABASE["games"].delete_one({"gameurl": gameurl})
        for i in range(1, 5):
            if str(i) in game.keys():
                if game[str(i)] == "":
                    client.DATABASE["games"].update_one(
                        {"gameurl": gameurl}, {"$unset": {str(i): ""}}
                    )  # This doesn't really serve a purpose
        if gamesummary["abilityRound"][
            "inProgress"
        ]:  # Initialization works differently depending on whether there is an ability in play or not
            waitingplayer = players[gamesummary["abilityRound"]["current"] - 1]["user"][
                "_id"
            ].strip()
            waitingplayername = players[gamesummary["abilityRound"]["current"] - 1][
                "user"
            ]["username"].strip()
            waitingno = gamesummary["abilityRound"]["current"] - 1
            abilitytext = " respond to"
        else:
            waitingplayer = players[gamesummary["turn"]["player"]["current"] - 1][
                "user"
            ]["_id"].strip()
            waitingplayername = players[gamesummary["turn"]["player"]["current"] - 1][
                "user"
            ]["username"].strip()
            waitingno = gamesummary["turn"]["player"]["current"] - 1
            abilitytext = ""
        if "0" in game.keys():
            if (
                waitingplayer in game["0"].keys()
            ):  # If we have records of the person the game is waiting on
                waitingaction = gamesummary["step"]
                gameround = gamesummary["round"]
                gamephase = gamesummary["phase"]
                gamename = gamesummary["name"]
                colour = players[waitingno]["color"]
                colour = colours[colour]
                embed = disnake.Embed(
                    title=gamename,
                    url=gameurl,
                    description=str(
                        f"Waiting for {waitingplayername} to{abilitytext}: {waitingaction}\nRound: {gameround}"
                    ),
                    color=colour,
                )  # This creates the embed that notifies people
                embed.set_author(
                    name="Twilight Imperium Reminder",
                    url=gameurl,
                    icon_url=f"https://www.twilightwars.com/img/faction/{players[waitingno]['faction'].replace(' ','%20')}/symbol-pixel.png",
                )
                if (
                    game["lastStep"] == str(gamesummary["step"]) + str(waitingplayer)
                    and str(gamesummary["step"]) + str(waitingplayer)
                    != game["justChanged"]
                ):  # This makes sure that the notification is only sent if it hasn't been sent yet and it has been at least 2 minutes since it changed
                    if game["0"][waitingplayer] != "":
                        await client.channel.send(
                            f"The game is waiting for {waitingplayername} <@{'> <@'.join(game['0'][waitingplayer].split(','))}>",
                            embed=embed,
                        )
                        print(f"{waitingplayername} was notified")
                    # else:
                    # print(waitingplayername+" didn't receive a notification.")
                    if "1" in game.keys():
                        if game["1"] != "":
                            await client.channel.send(
                                f"<@{'> <@'.join(game['1'].split(','))}> The game is waiting on {waitingplayername}",
                                embed=embed,
                            )
                    # client.DATABASE["games"].update_one({"gameurl":gameurl},{"$set":{"lastStep":str(gamesummary["step"])+str(waitingplayer),"justChanged":game["lastStep"]}})

                # elif game["lastStep"]==str(gamesummary["step"])+str(waitingplayer):
                # print(f"{waitingplayername} has already been notified")
                # else:
                # print(f"{waitingplayername} will receive a notification next cycle")
                # Updates the dictionary so that notifications are not sent twice
                client.DATABASE["games"].update_one(
                    {"gameurl": gameurl},
                    {
                        "$set": {
                            "lastStep": str(gamesummary["step"]) + str(waitingplayer),
                            "justChanged": game["lastStep"],
                        }
                    },
                )

            else:
                waitingaction = gamesummary["step"]
                gameround = gamesummary["round"]
                gamephase = gamesummary["phase"]
                gamename = gamesummary["name"]
                colour = players[waitingno]["color"]
                colour = colours[colour]

                embed = disnake.Embed(
                    title=gamename,
                    url=gameurl,
                    description=str(
                        f"Waiting for {waitingplayername} to{abilitytext}: {waitingaction}\nRound: {gameround}"
                    ),
                    color=colour,
                )
                embed.set_author(
                    name="Twilight Imperium Reminder",
                    url=gameurl,
                    icon_url=f"https://www.twilightwars.com/img/faction/{players[waitingno]['faction'].replace(' ','%20')}/symbol.png",
                )
                if (
                    game["lastStep"] == str(gamesummary["step"]) + str(waitingplayer)
                    and str(gamesummary["step"]) + str(waitingplayer)
                    != game["justChanged"]
                ):  # This makes sure that the notification is only sent if it hasn't been sent yet and it has been at least 2 minutes since it changed
                    if "1" in game.keys():
                        if game["1"] != "":
                            await client.channel.send(
                                f"<@{'> <@'.join(game['1'].split(','))}> The game is waiting on {waitingplayername}",
                                embed=embed,
                            )
                client.DATABASE["games"].update_one(
                    {"gameurl": gameurl},
                    {
                        "$set": {
                            "lastStep": str(gamesummary["step"]) + str(waitingplayer),
                            "justChanged": game["lastStep"],
                        }
                    },
                )
                # print(waitingplayername + " didn't receive a notification.")
        else:
            print("Something has gone horribly wrong")
        count = 0
        events = []
        lastLog = log[count]["_id"]
        # This very complicated seeming stack of statements just loop through each log until we reach the log that we saw before. It then sends notifications to anyone with notifications set for strategy cards or trade
        if log[count]["_id"] != game["lastLog"]:
            while log[count]["_id"] != game["lastLog"]:
                if "user" in log[count].keys():
                    for player in players:
                        if player["user"]["_id"] == log[count]["user"]:
                            if log[count]["event"] == "strategy card played":
                                if "2" in game.keys():
                                    if game["2"] != "":
                                        if (
                                            log[count]["details"]["strategyCard"]
                                            == "Trade"
                                        ):
                                            await client.channel.send(
                                                f"<@{'> <@'.join(game['2'].split(','))}>\nTrade Strategy Card played in {gamename}"
                                            )
                                if "3" in game.keys():
                                    if game["3"] != "":
                                        await client.channel.send(
                                            f"<@{'> <@'.join(game['3'].split(','))}>\n{log[count]['details']['strategyCard']} Strategy Card played in {gamename}"
                                        )
                            events.append(
                                f"{player['user']['username']}: {log[count]['event'].title()}."
                            )
                else:
                    events.append(f"{log[count]['event'].title()}.")
                count += 1
                if count >= len(log):
                    break
            client.DATABASE["games"].update_one(
                {"gameurl": gameurl}, {"$set": {"lastLog": lastLog}}
            )
        if "4" in game.keys():
            if game["4"] != "":
                for i in reversed(events):
                    await client.channel.send(
                        f"<@{'> <@'.join(game['4'].split(','))}>\n{i.title()[:-1]} in {gamename}"
                    )

    gameAsync = [getgames(x) for x in games]
    try:
        await asyncio.gather(*gameAsync)  # Does all the games asynchronously
    except:
        await client.dmchannel.send(f"Bot failed, restarting.")
        await client.session.close()
        await asyncio.sleep(60*10)
        await update.restart()
        return
    if len(client.deleted) < len(gameAsync) / 10:
        for gameurl, gamename, peopleinvolved in client.deleted:
            await client.channel.send(
                f"<@"
                + "> <@".join(peopleinvolved)
                + ">\n"
                + gamename
                + " has mysteriously disappeared"
            )
            client.DATABASE["games"].delete_one({"gameurl": gameurl})
            return
    # print("Update concluded")
    # print("Current users: "+", ".join([str((await client.fetch_user(int(x))).name) for x in users]))
    print("Number of users: " + str(len(users)))
    end = time.time()
    # print("Time taken: "+str(end-start))
    await client.session.close()
    payload = {"email": os.environ["EMAIL"], "password": os.environ["PASSWORD"]}
    client.session = aiohttp.ClientSession()
    await client.session.post("https://www.twilightwars.com/login", data=payload)


@client.event
async def on_ready():

    client.channel = await client.fetch_channel(970285338901745695)
    client.dmchannel = await client.fetch_user(560022746973601792)
    client.dmchannel = await client.dmchannel.create_dm()
    await client.dmchannel.send(f"CHOO")
    # await client.channel.send("I'm alive")
    # await asyncio.sleep(30)
    client.loop = asyncio.get_event_loop()
    payload = {"email": os.environ["EMAIL"], "password": os.environ["PASSWORD"]}
    client.session = aiohttp.ClientSession()
    async with client.session.post(
        "https://www.twilightwars.com/login", data=payload
    ) as response:
        if not update.is_running():
            update.start()


try:
    client.run(os.environ["DISCORD_TOKEN"])
except disnake.errors.HTTPException as e:
    print(e.response)
